"""LangGraph supervisor: route → research → assess → (research | code | answer) → answer.

Termination is guaranteed three ways: the loop guard (budgets, no progress, repeated calls), a cap on follow-up
research rounds, and LangGraph's recursion limit as a last resort (design §8.5).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from cortex.agents.agents import (
    Analyst,
    Coder,
    Researcher,
    RunState,
    StepResult,
    assess,
    extractive_fallback,
)
from cortex.agents.guard import LoopGuard
from cortex.agents.tools import RepeatedCall, Toolbox, ToolNotAllowed
from cortex.models.llm import LLM, CallContext
from cortex.observability import metrics
from cortex.observability.tracing import span
from cortex.router import Router

log = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], object]
MAX_FOLLOW_UPS = 2
_CALC = re.compile(
    r"\b(?:calculate|compute|how many|total|sum|average|percent(?:age)?|multiply|divide|ratio)\b",
    re.IGNORECASE,
)


class GraphState(TypedDict):
    run: RunState


@dataclass
class Supervisor:
    llm: LLM
    ctx: CallContext
    router: Router
    toolbox: Toolbox
    guard: LoopGuard
    emit: Emit
    on_token: Callable[[str], None] | None = None
    assess_enabled: bool = True

    def __post_init__(self) -> None:
        self.researcher = Researcher(self.toolbox)
        self.coder = Coder(self.toolbox, self.llm, self.ctx)
        self.analyst = Analyst(self.llm, self.ctx, self.on_token)
        self._assessments = 0
        self._graph = self._build()

    # ---- graph -----------------------------------------------------------------------------------------------
    def _build(self) -> Any:
        g = StateGraph(GraphState)
        g.add_node("route", self._route)
        g.add_node("research", self._research)
        g.add_node("assess", self._assess)
        g.add_node("code", self._code)
        g.add_node("answer", self._answer)
        g.add_edge(START, "route")
        g.add_edge("route", "research")
        g.add_conditional_edges("research", self._after_research, {"assess": "assess", "answer": "answer"})
        g.add_conditional_edges(
            "assess", self._after_assess, {"research": "research", "code": "code", "answer": "answer"}
        )
        g.add_edge("code", "answer")
        g.add_edge("answer", END)
        return g.compile()

    def run(self, question: str) -> RunState:
        state = RunState(question=question)
        with span("agent.run", tenant=self.ctx.tenant_id, task=self.ctx.task_id):
            out = self._graph.invoke(
                {"run": state}, config={"recursion_limit": 4 * self.guard.budget.max_steps + 8}
            )
        result: RunState = out["run"]
        if result.stop_reason:
            metrics.LOOP_GUARD.labels(reason=result.stop_reason).inc()
        return result

    # ---- nodes -----------------------------------------------------------------------------------------------
    def _route(self, state: GraphState) -> GraphState:
        run = state["run"]
        run.route = self.router.route(run.question)
        run.needs_code = bool(_CALC.search(run.question) and re.search(r"\d", run.question))
        self._step(
            run, StepResult("supervisor", f"route: {run.route}", 0, {"router": self.router.name}), count=False
        )
        return {"run": run}

    def _research(self, state: GraphState) -> GraphState:
        run = state["run"]
        try:
            result = self.researcher.run(run)
        except (RepeatedCall, ToolNotAllowed) as exc:
            self.guard.stop_reason = (
                "repeated_tool_call" if isinstance(exc, RepeatedCall) else "tool_not_allowed"
            )
            run.pending_query = None
            result = StepResult("researcher", "stopped", 0, {"error": str(exc)})
        self._step(run, result)
        if result.new_evidence:
            self.emit("evidence", {"items": [e.as_dict() for e in run.evidence[-result.new_evidence :]]})
        return {"run": run}

    def _after_research(self, state: GraphState) -> Literal["assess", "answer"]:
        run = state["run"]
        if self.guard.check(self.ctx.usage.total_tokens) or not run.evidence:
            return "answer"
        if (self.assess_enabled and self._assessments < MAX_FOLLOW_UPS) or run.needs_code:
            return "assess"
        return "answer"

    def _assess(self, state: GraphState) -> GraphState:
        run = state["run"]
        self._assessments += 1
        verdict = assess(self.llm, self.ctx, run) if self.assess_enabled else None
        if verdict is not None:
            run.needs_code = run.needs_code or verdict.needs_calculation
            q = (verdict.follow_up_query or "").strip()
            if not verdict.sufficient and q and q.lower() not in {x.lower() for x in run.queries}:
                run.pending_query = q
        self.guard.steps += (
            1  # assessing is a step but adds no evidence by design; it does not count as stall
        )
        self._step(
            run,
            StepResult(
                "supervisor",
                "assess evidence",
                0,
                {
                    "sufficient": None if verdict is None else verdict.sufficient,
                    "follow_up": run.pending_query,
                    "needs_code": run.needs_code,
                },
            ),
            count=False,
        )
        return {"run": run}

    def _after_assess(self, state: GraphState) -> Literal["research", "code", "answer"]:
        run = state["run"]
        if self.guard.check(self.ctx.usage.total_tokens):
            return "answer"
        if run.needs_code and run.code_result is None:
            return "code"
        if run.pending_query:
            return "research"
        return "answer"

    def _code(self, state: GraphState) -> GraphState:
        run = state["run"]
        try:
            result = self.coder.run(run)
        except (RepeatedCall, ToolNotAllowed) as exc:
            self.guard.stop_reason = "repeated_tool_call"
            result = StepResult("coder", "stopped", 0, {"error": str(exc)})
        self._step(run, result)
        if run.code is not None:
            self.emit("code", {"code": run.code, "result": run.code_result})
        return {"run": run}

    def _answer(self, state: GraphState) -> GraphState:
        run = state["run"]
        reason = self.guard.check(self.ctx.usage.total_tokens)
        run.stop_reason = reason
        run.partial = reason is not None
        if reason in ("token_budget", "wall_clock"):
            # No budget left for the large model: answer extractively, cited, and say so.
            run.answer = extractive_fallback(run)
            run.not_found = not run.evidence
            self._step(
                run,
                StepResult("analyst", "extractive answer (budget reached)", 0, {"reason": reason}),
                count=False,
            )
            return {"run": run}
        result = self.analyst.run(run)
        self._step(run, result, count=False)
        return {"run": run}

    # ---- bookkeeping -----------------------------------------------------------------------------------------
    def _step(self, run: RunState, result: StepResult, *, count: bool = True) -> None:
        if count:
            self.guard.record_step(result.new_evidence)
        u = self.ctx.usage
        entry = {
            "t": round(time.monotonic() - self.guard.started, 3),
            "agent": result.agent,
            "action": result.action,
            "new_evidence": result.new_evidence,
            "detail": result.detail,
            "steps_used": self.guard.steps,
            "tokens_used": u.total_tokens,
            "cost_usd": round(u.cost_usd, 6),
            "remaining": self.guard.remaining(u.total_tokens),
        }
        run.trace.append(entry)
        self.emit("step", entry)
