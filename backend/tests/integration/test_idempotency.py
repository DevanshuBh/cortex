"""Everything a redelivered task touches is safe to run twice (guide step 4.5, design §8.4)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from cortex.agents.guard import Budget, LoopGuard
from cortex.agents.tools import Toolbox
from cortex.db import repo
from cortex.db.session import tenant_session
from cortex.ingest.chunk import Chunk

pytestmark = pytest.mark.integration


def _answer(q: str = "q") -> dict[str, Any]:
    return {"question": q, "answer": "a [1]", "evidence": [], "route": "content", "partial": False,
            "not_found": False, "steps": 1, "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0,
            "latency_ms": 1}


def test_same_idempotency_key_returns_the_same_task(tenant: str) -> None:
    with tenant_session(tenant) as db:
        a, created_a = repo.create_task(db, tenant, "ask", {"question": "x"}, idempotency_key="key-12345678")
        b, created_b = repo.create_task(db, tenant, "ask", {"question": "x"}, idempotency_key="key-12345678")
        c, _ = repo.create_task(db, tenant, "ask", {"question": "x"})
    assert a == b and created_a and not created_b
    assert c != a


def test_finished_task_is_not_restarted_by_a_redelivered_message(tenant: str) -> None:
    with tenant_session(tenant) as db:
        tid, _ = repo.create_task(db, tenant, "ask", {"question": "x"})
        assert repo.start_task(db, tenant, tid) is not None
        repo.finish_task(db, tenant, tid, "succeeded", result={})
        assert repo.start_task(db, tenant, tid) is None
        repo.finish_task(db, tenant, tid, "failed", error="late duplicate")  # cannot overwrite success
        t = repo.get_task(db, tenant, tid)
    assert t is not None and t.status == "succeeded"


def test_one_answer_per_task(tenant: str) -> None:
    with tenant_session(tenant) as db:
        tid, _ = repo.create_task(db, tenant, "ask", {"question": "x"})
        assert repo.save_answer(db, tenant, tid, _answer("first"))
        assert not repo.save_answer(db, tenant, tid, _answer("second"))
        got = repo.get_answer(db, tenant, tid)
    assert got is not None and got["question"] == "first"


def test_replacing_chunks_twice_leaves_one_copy_with_stable_ids(tenant: str) -> None:
    chunks = [Chunk(i, "H", f"text {i}", i * 10, i * 10 + 6, 4, f"hash{i}") for i in range(3)]
    vec = "[" + ",".join(["0.1"] * 384) + "]"
    with tenant_session(tenant) as db:
        doc = repo.create_document(db, tenant, title="t", filename="t.md", mime="text/markdown", object_key="k",
                                   status="ready")
        first = repo.replace_chunks(db, tenant, doc, "v1", chunks, [vec] * 3)
    with tenant_session(tenant) as db:
        second = repo.replace_chunks(db, tenant, doc, "v1", chunks, [vec] * 3)
        n = db.execute(text("SELECT count(*) FROM chunks WHERE document_id = CAST(:d AS uuid)"), {"d": doc}).scalar()
    assert first == second and n == 3


def test_side_effecting_tool_runs_once_across_redelivery(tenant: str) -> None:
    runs: list[str] = []

    def run_code(args: dict[str, Any]) -> dict[str, Any]:
        runs.append(args["code"])
        return {"stdout": "42\n", "exit_code": 0}

    with tenant_session(tenant) as db:
        run_id, _ = repo.create_task(db, tenant, "ask", {"question": "x"})
    for _attempt in range(2):  # the original delivery, then the redelivery after a crash
        guard = LoopGuard(Budget(5, 1000, 2, 60))
        tb = Toolbox(tenant, run_id, guard, {"run_code": run_code})
        assert tb.call("coder", "run_code", {"code": "print(42)"}) == {"stdout": "42\n", "exit_code": 0}
    assert runs == ["print(42)"], "the sandbox ran only once; the redelivery replayed the recorded result"
