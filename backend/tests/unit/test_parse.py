from __future__ import annotations

import pytest

from cortex.ingest.parse import ParseError, mime_for, parse


def test_markdown_front_matter_title_and_heading_paths() -> None:
    raw = b"---\ntitle: Deployments\n---\nIntro text.\n\n## Use case\n\nBody.\n\n### Detail\n\nMore."
    doc = parse(raw, "text/markdown", "deployment.md")
    assert doc.title == "Deployments"
    assert [s.heading_path for s in doc.sections] == [
        "Deployments",
        "Deployments > Use case",
        "Deployments > Use case > Detail",
    ]
    for s in doc.sections:
        assert doc.text[s.char_start : s.char_start + len(s.text)] == s.text


def test_headings_inside_code_fences_are_not_headings() -> None:
    raw = b"# T\n\n```bash\n# not a heading\necho hi\n```\n"
    doc = parse(raw, "text/markdown", "t.md")
    assert len(doc.sections) == 1
    assert "# not a heading" in doc.sections[0].text


def test_html_drops_scripts_and_keeps_structure() -> None:
    html = b"<html><head><title>Guide</title><script>alert(1)</script></head><body><h1>Guide</h1><p>One.</p>" \
           b"<h2>Part</h2><ul><li>item</li></ul></body></html>"
    doc = parse(html, "text/html", "g.html")
    assert doc.title == "Guide"
    assert "alert" not in doc.text
    assert doc.sections[-1].heading_path == "Guide > Part"
    assert "- item" in doc.sections[-1].text


def test_plain_text_and_empty_documents() -> None:
    assert parse(b"hello world", "text/plain", "notes.txt").title == "notes"
    with pytest.raises(ParseError):
        parse(b"   \n\n ", "text/plain", "empty.txt")


def test_mime_detection_rejects_unknown_types() -> None:
    assert mime_for("a.MD") == "text/markdown"
    assert mime_for("x.bin", "application/pdf") == "application/pdf"
    with pytest.raises(ParseError):
        mime_for("malware.exe", "application/octet-stream")


def test_corrupt_pdf_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        parse(b"%PDF-1.7 not really a pdf", "application/pdf", "bad.pdf")
