from __future__ import annotations

import time

from cortex.agents.guard import Budget, LoopGuard


def guard(**kw: float) -> LoopGuard:
    b = {"max_steps": 5, "max_tokens": 1000, "no_progress_steps": 2, "wall_clock_seconds": 60.0, **kw}
    return LoopGuard(Budget(int(b["max_steps"]), int(b["max_tokens"]), int(b["no_progress_steps"]),
                            float(b["wall_clock_seconds"])))


def test_step_budget() -> None:
    g = guard(max_steps=2)
    g.record_step(1)
    assert g.check(0) is None
    g.record_step(1)
    assert g.check(0) == "step_budget"


def test_token_budget() -> None:
    assert guard().check(999) is None
    assert guard().check(1000) == "token_budget"


def test_no_progress_resets_on_new_evidence() -> None:
    g = guard(no_progress_steps=2)
    g.record_step(0)
    g.record_step(3)
    g.record_step(0)
    assert g.check(0) is None
    g.record_step(0)
    assert g.check(0) == "no_progress"


def test_repeated_tool_call_is_detected_regardless_of_key_order_and_case() -> None:
    g = guard()
    assert g.note_call("hybrid_search", {"query": "Pods", "k": 5})
    assert not g.note_call("hybrid_search", {"k": 5, "query": "pods"})
    assert g.check(0) == "repeated_tool_call"


def test_wall_clock() -> None:
    g = guard(wall_clock_seconds=0.01)
    time.sleep(0.02)
    assert g.check(0) == "wall_clock"
