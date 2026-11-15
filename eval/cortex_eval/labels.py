"""Labelled questions and chunk relevance.

Ground truth is a (document, exact quote) pair, not a chunk id: a chunk is relevant to an evidence item when it
belongs to that document and contains the quote. Labels therefore survive re-chunking (staff step S.2) and
re-embedding (S.6). Text is normalised the same way on both sides (case, whitespace, Markdown code/emphasis marks).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    return _WS.sub(" ", text.replace("`", "").replace("*", "")).strip().lower()


@dataclass(frozen=True, slots=True)
class EvidenceLabel:
    doc: str
    quote: str


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    type: str  # content | relationship | no_answer | adversarial
    question: str
    reference: str
    evidence: tuple[EvidenceLabel, ...]
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def answerable(self) -> bool:
        return self.type != "no_answer"


def load_questions(path: Path) -> list[Question]:
    out: list[Question] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        ev = tuple(EvidenceLabel(e["doc"], e["quote"]) for e in raw.get("evidence", []))
        extra = {k: v for k, v in raw.items() if k not in {"id", "type", "question", "reference", "evidence"}}
        out.append(Question(raw["id"], raw["type"], raw["question"], raw.get("reference", ""), ev, extra))
    return out


def doc_text_index(roots: Iterable[Path]) -> dict[str, str]:
    """Normalised full text of every corpus file, keyed by file name (the document's filename in CORTEX)."""
    docs: dict[str, str] = {}
    for root in roots:
        for f in root.glob("*.md"):
            docs[f.name] = normalise(f.read_text(encoding="utf-8"))
    return docs


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: str
    doc: str  # document filename
    text: str  # chunk text


def satisfied(evidence: Sequence[EvidenceLabel], chunk: RetrievedChunk) -> set[int]:
    """Indices of the evidence items this chunk satisfies."""
    text = normalise(chunk.text)
    base = chunk.doc.rsplit("/", 1)[-1]
    return {i for i, e in enumerate(evidence) if e.doc == base and normalise(e.quote) in text}
