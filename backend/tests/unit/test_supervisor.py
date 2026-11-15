"""Agent behaviour with a scripted model and fake tools: answers, grounding, termination, allow-lists."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from cortex.agents.agents import NOT_FOUND_TEXT, _NotFoundFilter
from cortex.agents.guard import Budget, LoopGuard
from cortex.agents.supervisor import Supervisor
from cortex.agents.tools import Toolbox, ToolNotAllowed
from cortex.config import Settings
from cortex.models.client import FakeClient, Message
from cortex.models.llm import LLM, CallContext
from cortex.router import RuleRouter


def chunk(i: int) -> dict[str, Any]:
    return {"chunk_id": f"c{i}", "document_id": "d1", "title": "Pods", "heading": "Pods > Overview",
            "text": f"Fact number {i}: a Pod runs one or more containers.", "source": "rerank"}


class Script:
    """Scripted model: reacts to which system prompt it receives."""

    def __init__(self, *, answer: str = "A Pod runs containers [1].", follow_ups: Sequence[str | None] = (),
                 needs_calc: bool = False) -> None:
        self.answer = answer
        self.follow_ups = list(follow_ups)
        self.needs_calc = needs_calc
        self.steps: list[str] = []

    def __call__(self, _model: str, messages: Sequence[Message]) -> str:
        system = messages[0].content
        if system.startswith("You check whether retrieved passages"):
            self.steps.append("assess")
            q = self.follow_ups.pop(0) if self.follow_ups else None
            return json.dumps({"sufficient": q is None, "follow_up_query": q, "needs_calculation": self.needs_calc})
        if system.startswith("You write a short Python 3 program"):
            self.steps.append("code")
            return "```python\nprint('total:', 3 * 2)\n```"
        if system.startswith("You are CORTEX"):
            self.steps.append("answer")
            return self.answer
        self.steps.append("other")
        return "{}"


def make(
    script: Script,
    tools: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
    *,
    max_steps: int = 8,
    max_tokens: int = 100_000,
    on_token: Callable[[str], None] | None = None,
) -> tuple[Supervisor, list[tuple[str, dict[str, Any]]]]:
    settings = Settings(model_provider="fake")
    llm = LLM(settings, {"fake": FakeClient(script)})
    ctx = CallContext(tenant_id="t1", log_calls=False)
    guard = LoopGuard(Budget(max_steps, max_tokens, 2, 60.0))
    events: list[tuple[str, dict[str, Any]]] = []
    sup = Supervisor(llm=llm, ctx=ctx, router=RuleRouter(), toolbox=Toolbox("t1", None, guard, tools, ledger=False),
                     guard=guard, emit=lambda e, d: events.append((e, d)), on_token=on_token)
    return sup, events


def hybrid_returning(*batches: list[int]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    calls = iter(batches)

    def search(_args: dict[str, Any]) -> dict[str, Any]:
        return {"chunks": [chunk(i) for i in next(calls, [])]}

    return search


def test_content_question_gets_a_cited_answer() -> None:
    script = Script()
    sup, events = make(script, {"hybrid_search": hybrid_returning([1, 2, 3])})
    run = sup.run("What is a Pod?")
    assert run.answer == "A Pod runs containers [1]."
    assert not run.not_found and not run.partial
    assert [e.chunk_id for e in run.evidence] == ["c1", "c2", "c3"]
    assert script.steps == ["assess", "answer"]
    assert [e for e, _ in events].count("step") >= 3


def test_no_evidence_means_not_found_without_calling_the_large_model() -> None:
    script = Script()
    sup, _ = make(script, {"hybrid_search": hybrid_returning([])})
    run = sup.run("What is the airspeed of an unladen swallow?")
    assert run.not_found and run.answer == NOT_FOUND_TEXT
    assert "answer" not in script.steps


def test_model_answer_without_citations_is_refused() -> None:
    sup, _ = make(Script(answer="Pods are probably containers."), {"hybrid_search": hybrid_returning([1])})
    run = sup.run("What is a Pod?")
    assert run.not_found


def test_looping_agent_stops_when_follow_ups_add_nothing() -> None:
    # The planner keeps asking new follow-up queries, but search keeps returning the same chunks.
    script = Script(follow_ups=["pods detail", "pods more detail", "pods even more", "and more"])
    sup, _ = make(script, {"hybrid_search": hybrid_returning([1], [1], [1], [1], [1])})
    run = sup.run("What is a Pod?")
    assert run.partial and run.stop_reason == "no_progress"
    assert run.answer.endswith("[1].")  # still answers from the evidence it has
    assert sup.guard.steps <= 8


def test_long_legitimate_task_is_not_stopped_early() -> None:
    script = Script(follow_ups=["second aspect", "third aspect"])
    sup, _ = make(script, {"hybrid_search": hybrid_returning([1, 2], [3, 4], [5, 6])})
    run = sup.run("Explain Pods, their lifecycle and their networking")
    assert not run.partial and run.stop_reason is None
    assert len(run.evidence) == 6
    assert run.queries == ["Explain Pods, their lifecycle and their networking", "second aspect", "third aspect"]


def test_step_budget_bounds_the_run() -> None:
    script = Script(follow_ups=["a", "b", "c", "d"])
    sup, _ = make(script, {"hybrid_search": hybrid_returning([1], [2], [3], [4], [5])}, max_steps=2)
    run = sup.run("What is a Pod?")
    assert run.partial and run.stop_reason == "step_budget"


def test_token_budget_gives_an_extractive_partial_answer_without_the_large_model() -> None:
    script = Script()
    sup, _ = make(script, {"hybrid_search": hybrid_returning([1, 2])}, max_tokens=1)
    run = sup.run("What is a Pod?")
    assert run.partial and run.stop_reason == "token_budget"
    assert "budget ran out" in run.answer and "[1]" in run.answer
    assert "answer" not in script.steps


def test_calculation_question_runs_the_coder_in_the_sandbox() -> None:
    ran: list[str] = []

    def run_code(args: dict[str, Any]) -> dict[str, Any]:
        ran.append(args["code"])
        return {"stdout": "total: 6\n", "stderr": "", "exit_code": 0, "timed_out": False}

    script = Script(answer="Three replicas on two nodes gives 6 Pods [1].")
    sup, events = make(script, {"hybrid_search": hybrid_returning([1]), "run_code": run_code})
    run = sup.run("Calculate the total pods for 3 replicas times 2 nodes")
    assert ran == ["print('total:', 3 * 2)"]
    assert run.code_result and run.code_result["stdout"] == "total: 6\n"
    assert "code" in [e for e, _ in events]


def test_tool_allow_lists_are_enforced_in_code() -> None:
    guard = LoopGuard(Budget(5, 1000, 2, 60))
    tb = Toolbox("t1", None, guard, {"hybrid_search": lambda a: {}, "run_code": lambda a: {}}, ledger=False)
    with pytest.raises(ToolNotAllowed):
        tb.call("analyst", "hybrid_search", {"query": "x"})
    with pytest.raises(ToolNotAllowed):
        tb.call("researcher", "run_code", {"code": "print(1)"})
    with pytest.raises(ToolNotAllowed):
        tb.call("coder", "hybrid_search", {"query": "x"})


def test_not_found_reply_is_never_streamed() -> None:
    out: list[str] = []
    f = _NotFoundFilter(out.append)
    for piece in ["NOT", "_FO", "UND", " anything"]:
        f.feed(piece)
    assert out == []
    out2: list[str] = []
    g = _NotFoundFilter(out2.append)
    for piece in ["A Pod", " runs [1]."]:
        g.feed(piece)
    assert "".join(out2) == "A Pod runs [1]."
