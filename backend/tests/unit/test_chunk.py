from __future__ import annotations

import pytest

from cortex.ingest.chunk import chunk_document, embed_text
from cortex.ingest.parse import parse


def words(text: str) -> int:
    """Stand-in tokenizer: one token per whitespace-separated word, plus 2 specials like [CLS]/[SEP]."""
    return len(text.split()) + 2


def md(n_paragraphs: int, words_each: int, heading: str = "## Section") -> bytes:
    paras = [" ".join(f"w{p}_{i}" for i in range(words_each)) + "." for p in range(n_paragraphs)]
    return (f"# Title\n\n{heading}\n\n" + "\n\n".join(paras)).encode()


def test_no_chunk_exceeds_the_model_limit_even_with_heading() -> None:
    doc = parse(md(30, 40), "text/markdown", "a.md")
    chunks = chunk_document(doc, words, max_tokens=100, overlap_tokens=20, model_limit=128)
    assert chunks
    assert all(c.token_count <= 100 for c in chunks)
    assert all(words(c.embed_text) == c.token_count for c in chunks)


def test_chunk_offsets_point_at_the_document_text() -> None:
    doc = parse(md(10, 30), "text/markdown", "a.md")
    for c in chunk_document(doc, words, max_tokens=80, overlap_tokens=15, model_limit=128):
        assert doc.text[c.char_start : c.char_end] == c.text


def test_consecutive_chunks_overlap_by_whole_paragraphs() -> None:
    doc = parse(md(12, 20), "text/markdown", "a.md")
    chunks = chunk_document(doc, words, max_tokens=80, overlap_tokens=30, model_limit=128)
    assert len(chunks) > 2
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.char_start < a.char_end, "expected overlap between neighbouring chunks"
        assert b.char_start > a.char_start, "chunking must always make progress"


def test_oversized_paragraph_is_split_not_truncated() -> None:
    doc = parse(md(1, 500), "text/markdown", "a.md")
    chunks = chunk_document(doc, words, max_tokens=60, overlap_tokens=0, model_limit=64)
    covered = " ".join(c.text for c in chunks).split()
    assert covered == doc.sections[0].text.split(), "every word must land in some chunk"
    assert all(c.token_count <= 60 for c in chunks)


def test_chunks_do_not_cross_sections() -> None:
    raw = b"# T\n\n## A\n\nalpha text here.\n\n## B\n\nbeta text here."
    chunks = chunk_document(parse(raw, "text/markdown", "t.md"), words, max_tokens=200, overlap_tokens=0,
                            model_limit=256)
    assert [c.heading_path for c in chunks] == ["T > A", "T > B"]
    assert chunks[0].embed_text == embed_text("T > A", "alpha text here.")


def test_content_hash_is_deterministic_and_content_sensitive() -> None:
    a = chunk_document(parse(md(3, 10), "text/markdown", "a.md"), words, max_tokens=50, overlap_tokens=0,
                       model_limit=64)
    b = chunk_document(parse(md(3, 10), "text/markdown", "a.md"), words, max_tokens=50, overlap_tokens=0,
                       model_limit=64)
    assert [c.content_hash for c in a] == [c.content_hash for c in b]
    changed = chunk_document(parse(md(3, 10).replace(b"w1_3", b"CHANGED"), "text/markdown", "a.md"), words,
                             max_tokens=50, overlap_tokens=0, model_limit=64)
    assert [c.content_hash for c in a] != [c.content_hash for c in changed]


def test_budget_above_model_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="input limit"):
        chunk_document(parse(md(1, 5), "text/markdown", "a.md"), words, max_tokens=600, overlap_tokens=0,
                       model_limit=512)
