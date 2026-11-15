"""Prepare the evaluation corpus: Kubernetes "Concepts" pages and glossary entries (CC BY 4.0).

Reads a checkout of github.com/kubernetes/website at a pinned commit and writes clean Markdown to
``corpus/kubernetes/`` (Hugo shortcodes resolved to plain text, front matter reduced to a title and summary).

    git clone --depth 1 --filter=blob:none --sparse https://github.com/kubernetes/website.git k8s-website
    cd k8s-website && git checkout <commit> && git sparse-checkout set content/en/docs/concepts \
        content/en/docs/reference/glossary
    python scripts/prepare_corpus.py path/to/k8s-website
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PINNED_COMMIT = "109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3"
OUT = Path(__file__).resolve().parents[1] / "corpus" / "kubernetes"

FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
GLOSSARY_TOOLTIP = re.compile(r"\{\{<\s*glossary_tooltip\s+([^>]*?)>\}\}")
ATTR = re.compile(r'(\w+)="([^"]*)"')
FEATURE_STATE = re.compile(r"\{\{<\s*feature-state\s+([^>]*?)>\}\}")
CALLOUT_OPEN = re.compile(r"\{\{[<%]\s*(note|caution|warning)\s*[>%]\}\}", re.IGNORECASE)
CALLOUT_CLOSE = re.compile(r"\{\{[<%]\s*/(note|caution|warning)\s*[>%]\}\}", re.IGNORECASE)
HEADING_SC = re.compile(r'\{\{%\s*heading\s+"([^"]+)"\s*%\}\}')
CODE_SAMPLE = re.compile(r"\{\{[<%]\s*code_sample\s+([^>%]*?)[>%]\}\}")
GLOSSARY_DEF = re.compile(r"\{\{<\s*glossary_definition\s+([^>]*?)>\}\}")
PARAM = re.compile(r'\{\{<\s*param\s+"?([\w.]+)"?\s*>\}\}')
SKEW = re.compile(r'\{\{<\s*skew\s+(\w+)\s*>\}\}')
ANY_SC = re.compile(r"\{\{[<%].*?[>%]\}\}", re.DOTALL)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
MERMAID = re.compile(r"\{\{<\s*mermaid\s*>\}\}.*?\{\{<\s*/mermaid\s*>\}\}", re.DOTALL)
FIGURE = re.compile(r"\{\{<\s*figure\s+([^>]*?)>\}\}")
HEADING_NAMES = {"whatsnext": "What's next", "prerequisites": "Before you begin", "objectives": "Objectives",
                 "synopsis": "Synopsis", "options": "Options", "seealso": "See also"}
PARAMS = {"version": "v1.36", "fullversion": "v1.36.0", "skew currentVersion": "1.36"}


def _attrs(s: str) -> dict[str, str]:
    return dict(ATTR.findall(s))


def _term_label(term_id: str) -> str:
    return term_id.replace("-", " ")


def clean(raw: str, glossary: dict[str, str]) -> tuple[str, str, str]:
    title, summary = "", ""
    m = FRONT.match(raw)
    if m:
        fm = m.group(1)
        t = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", fm, re.MULTILINE)
        title = t.group(1).strip() if t else ""
        d = re.search(r"^(?:description|short_description):\s*>?-?\s*\n?((?:\s{2,}.+\n?)+|.+)$", fm, re.MULTILINE)
        if d:
            summary = " ".join(x.strip() for x in d.group(1).splitlines()).strip().strip("'\"")
        raw = raw[m.end():]
    body = HTML_COMMENT.sub("", raw)
    body = MERMAID.sub("[diagram omitted]", body)
    body = GLOSSARY_TOOLTIP.sub(lambda m: _attrs(m.group(1)).get("text") or _term_label(_attrs(m.group(1)).get("term_id", "")), body)
    body = FEATURE_STATE.sub(lambda m: "(Feature state: Kubernetes " + " ".join(
        f"{k}={v}" for k, v in _attrs(m.group(1)).items() if k in ("for_k8s_version", "state")) + ")", body)
    body = CALLOUT_OPEN.sub(lambda m: f"**{m.group(1).capitalize()}:** ", body)
    body = CALLOUT_CLOSE.sub("", body)
    body = HEADING_SC.sub(lambda m: HEADING_NAMES.get(m.group(1), m.group(1).capitalize()), body)
    body = CODE_SAMPLE.sub(lambda m: f"(Example manifest: {_attrs(m.group(1)).get('file', 'example')})", body)
    body = GLOSSARY_DEF.sub(lambda m: glossary.get(_attrs(m.group(1)).get("term_id", ""), ""), body)
    body = FIGURE.sub(lambda m: f"[figure: {_attrs(m.group(1)).get('alt') or _attrs(m.group(1)).get('caption', '')}]", body)
    body = PARAM.sub(lambda m: PARAMS.get(m.group(1), m.group(1)), body)
    body = SKEW.sub(lambda m: PARAMS.get(f"skew {m.group(1)}", m.group(1)), body)
    body = ANY_SC.sub("", body)
    body = body.replace("<!--more-->", "")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return title, summary, body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("checkout", type=Path)
    args = ap.parse_args()
    root: Path = args.checkout
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != PINNED_COMMIT:
        print(f"warning: checkout is at {head}, the evaluation set was labelled at {PINNED_COMMIT}", file=sys.stderr)
    docs = root / "content" / "en" / "docs"
    glossary_dir = docs / "reference" / "glossary"
    glossary: dict[str, str] = {}
    for f in glossary_dir.glob("*.md"):
        _t, summary, body = clean(f.read_text(encoding="utf-8"), {})
        glossary[f.stem] = summary or body.split("\n\n")[0]
    OUT.mkdir(parents=True, exist_ok=True)
    written = 0
    for f in sorted([*(docs / "concepts").rglob("*.md"), *glossary_dir.glob("*.md")]):
        if f.name == "_index.md" and f.stat().st_size < 400:
            continue
        rel = f.relative_to(docs)
        title, summary, body = clean(f.read_text(encoding="utf-8"), glossary)
        if not body or len(body) < 40:
            continue
        if rel.parts[0] == "reference":
            title = f"Glossary: {title}"
        name = "__".join(rel.with_suffix("").parts).replace("_index", "index") + ".md"
        source = f"https://github.com/kubernetes/website/blob/{head}/content/en/docs/{rel.as_posix()}"
        text = f"# {title}\n\n" + (f"{summary}\n\n" if summary and summary not in body[:400] else "") + body + "\n"
        text += f"\n<!-- source: {source} -->\n"
        (OUT / name).write_text(text, encoding="utf-8")
        written += 1
    (OUT.parent / "NOTICE.md").write_text(
        "# Corpus notice\n\nThese files are derived from the Kubernetes documentation "
        f"(https://github.com/kubernetes/website, commit {head}), © The Kubernetes Authors, licensed under "
        "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).\n\nChanges: Hugo shortcodes were resolved to "
        "plain text, front matter was reduced to a title and summary, and files were renamed by path. "
        "Each file ends with a comment linking its source.\n",
        encoding="utf-8",
    )
    print(f"wrote {written} documents to {OUT}")


if __name__ == "__main__":
    main()
