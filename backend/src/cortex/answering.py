"""Answer one question for one tenant: wire tools, run the supervisor, produce the answer record."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from cortex.agents.guard import Budget, LoopGuard
from cortex.agents.supervisor import Supervisor
from cortex.agents.tools import Toolbox, ToolFn
from cortex.config import get_settings
from cortex.db import repo
from cortex.db.session import tenant_session
from cortex.models.llm import LLM, CallContext, get_llm
from cortex.observability import metrics
from cortex.retrieval.base import Candidate, Retriever
from cortex.router import LLMRouter, Router, RuleRouter

log = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], object]


class TaskCancelled(Exception):
    pass


def _chunk_dicts(tenant_id: str, cands: list[Candidate]) -> list[dict[str, Any]]:
    with tenant_session(tenant_id) as db:
        rows = {r.id: r for r in repo.get_chunks(db, tenant_id, [c.chunk_id for c in cands])}
    out = []
    for c in cands:
        r = rows.get(c.chunk_id)
        if r is None:  # deleted between search and fetch, or another tenant's id: never surfaces
            continue
        out.append(
            {
                "chunk_id": r.id,
                "document_id": r.document_id,
                "title": r.document_title,
                "heading": r.heading_path,
                "text": r.text,
                "source": c.source,
                "score": c.score,
            }
        )
    return out


def build_tools(
    tenant_id: str,
    retriever: Retriever,
    graph: Any | None,
    run_code: Callable[[str], dict[str, Any]] | None,
    k: int,
) -> dict[str, ToolFn]:
    def hybrid_search(args: dict[str, Any]) -> dict[str, Any]:
        return {"chunks": _chunk_dicts(tenant_id, retriever.search(tenant_id, str(args["query"]), k))}

    tools: dict[str, ToolFn] = {"hybrid_search": hybrid_search}

    if graph is not None:

        def graph_search(args: dict[str, Any]) -> dict[str, Any]:
            try:
                res = graph.search_paths(tenant_id, str(args["query"]))
            except Exception as exc:  # degrade to hybrid retrieval if Neo4j is down (design §9)
                log.warning("graph search failed: %s", exc)
                return {"chunks": [], "paths": [], "error": "graph unavailable"}
            paths = [
                {"text": p.describe(), "nodes": p.nodes, "relations": p.relations, "chunk_ids": p.chunk_ids}
                for p in res.paths[:15]
            ]
            return {"chunks": _chunk_dicts(tenant_id, res.candidates(k)), "paths": paths, "seeds": res.seeds}

        tools["graph_search"] = graph_search

    if run_code is not None:

        def run_code_tool(args: dict[str, Any]) -> dict[str, Any]:
            return run_code(str(args["code"]))

        tools["run_code"] = run_code_tool
    return tools


def answer_question(
    tenant_id: str,
    question: str,
    *,
    task_id: str | None = None,
    emit: Emit | None = None,
    on_token: Callable[[str], None] | None = None,
    retriever: Retriever | None = None,
    graph: Any | None = None,
    run_code: Callable[[str], dict[str, Any]] | None = None,
    llm: LLM | None = None,
    router: Router | str | None = None,
    confidential: bool | None = None,
    cancelled: Callable[[], bool] | None = None,
    log_calls: bool = True,
    assess_enabled: bool = True,
) -> dict[str, Any]:
    s = get_settings()
    started = time.perf_counter()
    llm = llm or get_llm()
    if confidential is None:
        with tenant_session(tenant_id) as db:
            confidential = repo.tenant_is_confidential(db, tenant_id)
    ctx = CallContext(tenant_id=tenant_id, task_id=task_id, confidential=confidential, log_calls=log_calls)
    retr: Retriever
    if retriever is None:
        from cortex.retrieval.pipeline import build_retriever

        retr = build_retriever("reranked")
    else:
        retr = retriever
    if graph is None:
        from cortex.graph.retrieve import GraphRetriever

        graph = GraphRetriever()
    if run_code is None:
        from cortex.sandbox.client import run_code as sandbox_run

        run_code = sandbox_run
    if router is None or router == "llm":
        router_impl: Router = LLMRouter(llm, ctx)
    elif router == "rules":
        router_impl = RuleRouter()
    else:
        assert not isinstance(router, str)
        router_impl = router

    guard = LoopGuard(
        Budget(s.agent_max_steps, s.agent_max_tokens, s.agent_no_progress_steps, s.agent_wall_clock_seconds)
    )
    toolbox = Toolbox(
        tenant_id,
        task_id,
        guard,
        build_tools(tenant_id, retr, graph, run_code, s.rerank_top_n),
        ledger=log_calls,
    )
    emit_fn = emit or (lambda _e, _d: None)

    def checked_emit(event: str, data: dict[str, Any]) -> None:
        if cancelled and cancelled():
            raise TaskCancelled
        emit_fn(event, data)

    def checked_token(piece: str) -> None:
        if cancelled and cancelled():
            raise TaskCancelled
        if on_token:
            on_token(piece)

    sup = Supervisor(
        llm=llm,
        ctx=ctx,
        router=router_impl,
        toolbox=toolbox,
        guard=guard,
        emit=checked_emit,
        on_token=checked_token,
        assess_enabled=assess_enabled,
    )
    run = sup.run(question)
    latency_ms = int((time.perf_counter() - started) * 1000)
    outcome = "not_found" if run.not_found else ("partial" if run.partial else "answered")
    metrics.ANSWERS.labels(route=run.route, outcome=outcome).inc()
    metrics.QUERY_COST.observe(ctx.usage.cost_usd)
    return {
        "question": question,
        "answer": run.answer,
        "evidence": [e.as_dict() for e in run.evidence],
        "graph_paths": run.graph_paths[:15],
        "route": run.route,
        "partial": run.partial,
        "not_found": run.not_found,
        "stop_reason": run.stop_reason,
        "steps": guard.steps,
        "input_tokens": ctx.usage.input_tokens,
        "output_tokens": ctx.usage.output_tokens,
        "cost_usd": round(ctx.usage.cost_usd, 6),
        "llm_calls": ctx.usage.calls,
        "latency_ms": latency_ms,
        "code": run.code,
        "code_result": run.code_result,
        "trace": run.trace,
        "tool_calls": toolbox.calls,
    }
