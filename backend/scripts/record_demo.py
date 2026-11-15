"""Record real CORTEX answers for the static demo (GitHub Pages has no model server).

Runs the full pipeline — router, agents, retrieval, graph, grounding gate — for each question and writes every event
the UI would have streamed, with its timing, to ``web/src/mocks/recorded.json``. The demo replays exactly these.

    docker compose run --rm -v "$PWD/web/src/mocks:/out" migrate \
        python scripts/record_demo.py k8s-docs /out/recorded.json "question one" "question two" ...
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cortex.answering import answer_question
from cortex.config import get_settings


def record(tenant: str, question: str) -> dict[str, Any]:
    started = time.perf_counter()
    events: list[dict[str, Any]] = []

    def at() -> float:
        return round(time.perf_counter() - started, 2)

    def emit(event: str, data: dict[str, Any]) -> None:
        events.append({"t": at(), "event": event, "data": data})

    def on_token(piece: str) -> None:
        events.append({"t": at(), "event": "token", "data": {"text": piece}})

    res = answer_question(tenant, question, emit=emit, on_token=on_token, log_calls=False)
    answer = {
        k: res[k]
        for k in (
            "answer",
            "evidence",
            "graph_paths",
            "route",
            "partial",
            "not_found",
            "stop_reason",
            "steps",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "latency_ms",
        )
    }
    events.append({"t": at(), "event": "answer", "data": answer})
    return {"question": question, "events": events}


def main() -> None:
    tenant, out, *questions = sys.argv[1:]
    s = get_settings()
    scenarios = []
    for q in questions:
        print(f"recording: {q}", flush=True)
        sc = record(tenant, q)
        ans = sc["events"][-1]["data"]
        print(
            f"  route={ans['route']} not_found={ans['not_found']} evidence={len(ans['evidence'])} "
            f"latency={ans['latency_ms']} ms",
            flush=True,
        )
        scenarios.append(sc)
    doc = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tenant": tenant,
        "models": {"small": s.model_small, "large": s.model_large},
        "scenarios": scenarios,
    }
    Path(out).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(scenarios)} scenarios to {out}")


if __name__ == "__main__":
    main()
