"""Extract text from PDF, Markdown, HTML and plain text into heading-aware sections.

Every section keeps its character offset in the document's normalised text, so a citation can be highlighted.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

SUPPORTED_MIME = {
    "application/pdf": "pdf",
    "text/markdown": "markdown",
    "text/x-markdown": "markdown",
    "text/html": "html",
    "text/plain": "text",
}
EXTENSIONS = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
}


class ParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Section:
    heading_path: str  # e.g. "Deployments > Rolling back a Deployment" or "Page 3"
    text: str
    char_start: int  # offset of text in ParsedDocument.text


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    title: str
    text: str
    sections: list[Section]


def mime_for(filename: str, declared: str | None = None) -> str:
    if declared and declared.split(";")[0].strip() in SUPPORTED_MIME:
        return declared.split(";")[0].strip()
    for ext, mime in EXTENSIONS.items():
        if filename.lower().endswith(ext):
            return mime
    raise ParseError(f"unsupported file type: {filename} ({declared})")


def parse(data: bytes, mime: str, filename: str) -> ParsedDocument:
    kind = SUPPORTED_MIME.get(mime)
    if kind == "pdf":
        return _parse_pdf(data, filename)
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        raw = data.decode("latin-1")
    if kind == "markdown":
        return _parse_markdown(raw, filename)
    if kind == "html":
        return _parse_html(raw, filename)
    if kind == "text":
        return _build(_stem(filename), [("", raw)])
    raise ParseError(f"unsupported mime type: {mime}")


def _stem(filename: str) -> str:
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return base.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip() or "Untitled"


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _build(title: str, parts: list[tuple[str, str]]) -> ParsedDocument:
    """Join (heading_path, text) parts into one normalised text with section offsets."""
    sections: list[Section] = []
    buf: list[str] = []
    pos = 0
    for heading, body in parts:
        body = _clean(body)
        if not body:
            continue
        if buf:
            buf.append("\n\n")
            pos += 2
        sections.append(Section(heading, body, pos))
        buf.append(body)
        pos += len(body)
    if not sections:
        raise ParseError("document contains no extractable text")
    return ParsedDocument(title=title.strip() or "Untitled", text="".join(buf), sections=sections)


_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _parse_markdown(raw: str, filename: str) -> ParsedDocument:
    raw = _HTML_COMMENT.sub("", raw.replace("\r\n", "\n"))
    title = ""
    m = _FRONT_MATTER.match(raw)
    if m:
        t = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", m.group(1), re.MULTILINE)
        title = t.group(1) if t else ""
        raw = raw[m.end() :]
    stack: list[tuple[int, str]] = []
    parts: list[tuple[str, str]] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        if current:
            parts.append((" > ".join(h for _, h in stack), "\n".join(current)))
            current.clear()

    for line in raw.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            current.append(line)
            continue
        h = None if in_fence else _HEADING.match(line)
        if h:
            flush()
            level, heading = len(h.group(1)), h.group(2).strip()
            if level == 1 and not title:
                title = heading
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
            continue
        current.append(line)
    flush()
    title = title or _stem(filename)
    # Prefix heading paths with the document title so a chunk says where it came from.
    titled = [
        (f"{title} > {hp}" if hp and not hp.startswith(title) else (hp or title), body) for hp, body in parts
    ]
    return _build(title, titled)


def _parse_html(raw: str, filename: str) -> ParsedDocument:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "svg", "form"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    body = soup.body or soup
    stack: list[tuple[int, str]] = []
    parts: list[tuple[str, str]] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            parts.append((" > ".join(h for _, h in stack), "\n\n".join(current)))
            current.clear()

    for el in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "td", "blockquote"]):
        if el.name and el.name[0] == "h" and el.name[1:].isdigit():
            flush()
            level = int(el.name[1])
            heading = el.get_text(" ", strip=True)
            if level == 1 and not title:
                title = heading
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
        elif el.find_parent(["li", "td", "blockquote"]) is None or el.name in ("li", "td"):
            text = el.get_text(" ", strip=True) if el.name != "pre" else el.get_text()
            if text:
                current.append(("- " + text) if el.name == "li" else text)
    flush()
    return _build(title or _stem(filename), parts)


def _parse_pdf(data: bytes, filename: str) -> ParsedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParseError("encrypted PDFs are not supported")
        meta_title = (reader.metadata.title if reader.metadata else None) or ""
        parts = [(f"Page {i}", page.extract_text() or "") for i, page in enumerate(reader.pages, start=1)]
    except PdfReadError as exc:
        raise ParseError(f"unreadable PDF: {exc}") from exc
    return _build(str(meta_title) or _stem(filename), parts)
