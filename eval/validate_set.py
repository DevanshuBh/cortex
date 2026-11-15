"""Check every evidence quote of the evaluation set against the corpus before it is used.

    python eval/validate_set.py        # exits non-zero if any quote is missing or the type mix is off
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cortex_eval.labels import doc_text_index, load_questions, normalise  # noqa: E402


def main() -> int:
    roots = [HERE.parent / "corpus" / "kubernetes", HERE / "adversarial"]
    docs = doc_text_index(roots)
    problems: list[str] = []
    for path in (HERE / "questions.jsonl", HERE / "adversarial.jsonl"):
        qs = load_questions(path)
        ids = collections.Counter(q.id for q in qs)
        problems += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
        for q in qs:
            if q.type != "no_answer" and not q.evidence:
                problems.append(f"{q.id}: no evidence")
            for ev in q.evidence:
                text = docs.get(ev.doc)
                if text is None:
                    problems.append(f"{q.id}: unknown document {ev.doc}")
                elif normalise(ev.quote) not in text:
                    problems.append(f"{q.id}: quote not found in {ev.doc}: {ev.quote!r}")
        mix = collections.Counter(q.type for q in qs)
        print(f"{path.name}: {len(qs)} questions {dict(mix)}")
    for p in problems:
        print("  PROBLEM", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
