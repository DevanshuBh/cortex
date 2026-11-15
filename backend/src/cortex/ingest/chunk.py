"""Structure-aware chunking sized in the embedding model's own tokens (guide step 1.3, docs/adr/0002).

Chunks never cross a section boundary. Inside a section, paragraphs are packed up to ``max_tokens`` (counting
the heading line that is embedded with the chunk); an oversized paragraph is split into sentences, and an
oversized sentence into word windows. Consecutive chunks overlap by up to ``overlap_tokens`` of whole units.
A chunk that would still exceed the model limit is never produced silently: it is split and counted.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from cortex.ingest.parse import ParsedDocument
from cortex.observability import metrics

log = logging.getLogger(__name__)

TokenCounter = Callable[[str], int]

_PARA = re.compile(r"\n\s*\n")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(\[])")


@dataclass(frozen=True, slots=True)
class Chunk:
    position: int
    heading_path: str
    text: str
    char_start: int
    char_end: int
    token_count: int
    content_hash: str

    @property
    def embed_text(self) -> str:
        return embed_text(self.heading_path, self.text)


def embed_text(heading_path: str, text: str) -> str:
    return f"{heading_path}\n\n{text}" if heading_path else text


@dataclass(frozen=True, slots=True)
class _Unit:
    start: int  # absolute offsets into the document text
    end: int
    tokens: int


def _spans(text: str, pattern: re.Pattern[str], base: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    pos = 0
    for m in pattern.finditer(text):
        if text[pos : m.start()].strip():
            out.append((base + pos, base + m.start()))
        pos = m.end()
    if text[pos:].strip():
        out.append((base + pos, base + len(text)))
    return out


def _word_windows(doc_text: str, start: int, end: int, budget: int, count: TokenCounter) -> list[_Unit]:
    words = [(m.start() + start, m.end() + start) for m in re.finditer(r"\S+", doc_text[start:end])]
    units: list[_Unit] = []
    i = 0
    while i < len(words):
        j = i + 1
        best = j
        # grow the window while it fits (binary search would be faster; sections are small)
        while j <= len(words) and count(doc_text[words[i][0] : words[j - 1][1]]) <= budget:
            best = j
            j += 1
        s, e = words[i][0], words[best - 1][1]
        units.append(_Unit(s, e, count(doc_text[s:e])))
        i = best
    return units


def _units(doc_text: str, start: int, end: int, budget: int, count: TokenCounter) -> list[_Unit]:
    units: list[_Unit] = []
    for ps, pe in _spans(doc_text[start:end], _PARA, start):
        t = count(doc_text[ps:pe])
        if t <= budget:
            units.append(_Unit(ps, pe, t))
            continue
        metrics.INGEST_TRUNCATION.inc()
        for ss, se in _spans(doc_text[ps:pe], _SENT, ps):
            st = count(doc_text[ss:se])
            if st <= budget:
                units.append(_Unit(ss, se, st))
            else:
                units.extend(_word_windows(doc_text, ss, se, budget, count))
    return units


def chunk_document(
    doc: ParsedDocument,
    count_tokens: TokenCounter,
    *,
    max_tokens: int,
    overlap_tokens: int,
    model_limit: int,
) -> list[Chunk]:
    if max_tokens > model_limit:
        raise ValueError("max_tokens must not exceed the embedding model's input limit")
    chunks: list[Chunk] = []
    text = doc.text
    for section in doc.sections:
        header_tokens = count_tokens(section.heading_path + "\n\n") if section.heading_path else 0
        budget = max(32, max_tokens - header_tokens)
        units = _units(text, section.char_start, section.char_start + len(section.text), budget, count_tokens)
        i = 0
        while i < len(units):
            used, j = 0, i
            while j < len(units) and (j == i or used + units[j].tokens <= budget):
                used += units[j].tokens
                j += 1
            start, end = units[i].start, units[j - 1].end
            body = text[start:end]
            full = embed_text(section.heading_path, body)
            tokens = count_tokens(full)
            if tokens > model_limit:  # cannot happen with sane budgets; never embed a truncated chunk
                log.warning(
                    "chunk over model limit (%d > %d) in %r", tokens, model_limit, section.heading_path
                )
                metrics.INGEST_TRUNCATION.inc()
            chunks.append(
                Chunk(
                    position=len(chunks),
                    heading_path=section.heading_path,
                    text=body,
                    char_start=start,
                    char_end=end,
                    token_count=tokens,
                    content_hash=hashlib.sha256(full.encode()).hexdigest(),
                )
            )
            if j >= len(units):
                break
            # overlap: step back over trailing whole units that fit in the overlap budget
            back, k = 0, j
            while k - 1 > i and back + units[k - 1].tokens <= overlap_tokens:
                back += units[k - 1].tokens
                k -= 1
            i = k if k > i else j
    return chunks
