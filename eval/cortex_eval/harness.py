"""Run the evaluation: retrieval ablations, full answers, router accuracy; write dated reports.

Every number carries a 95 % bootstrap interval, comparisons are paired, and a run is compared with the previous
report of the same name so a regression fails the nightly job (guide step 2.2, staff step S.1).
"""

from __future__ import annotations

import json
import subprocess
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cortex_eval.labels import Question, RetrievedChunk, satisfied
from cortex_eval.metrics import (
    Interval,
    bootstrap_ci,
    mean,
    paired_compare,
    percentile,
    score_ranking,
)

REPORTS = Path(__file__).resolve().parents[1] / "reports"


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


# ------------------------------------------------------------------------------------------------- retrieval
Search = Callable[[str], list[RetrievedChunk]]


@dataclass
class QuestionResult:
    id: str
    type: str
    recall: dict[int, float]
    mrr: float
    ndcg10: float
    latency_ms: float
    retrieved: list[str] = field(default_factory=list)


def chunk_lookup(tenant: str) -> Callable[[list[str]], list[RetrievedChunk]]:
    from cortex.db import repo
    from cortex.db.session import tenant_session

    def fetch(ids: list[str]) -> list[RetrievedChunk]:
        with tenant_session(tenant) as db:
            rows = repo.get_chunks(db, tenant, ids)
        return [RetrievedChunk(r.id, r.filename, r.text) for r in rows]

    return fetch


def run_retrieval(questions: Sequence[Question], search: Search, k: int = 10) -> list[QuestionResult]:
    out = []
    for q in questions:
        if not q.answerable:
            continue
        t0 = time.perf_counter()
        ranked = search(q.question)[:k]
        latency = (time.perf_counter() - t0) * 1000
        s = score_ranking(q.evidence, ranked)
        out.append(QuestionResult(q.id, q.type, s.recall, s.mrr, s.ndcg10, latency, [c.chunk_id for c in ranked]))
    return out


def summarise(results: Sequence[QuestionResult]) -> dict[str, Any]:
    def ci(values: list[float]) -> dict[str, float]:
        iv = bootstrap_ci(values)
        return {"value": iv.value, "low": iv.low, "high": iv.high}

    lat = [r.latency_ms for r in results]
    summary: dict[str, Any] = {
        "n": len(results),
        "recall@1": ci([r.recall[1] for r in results]),
        "recall@3": ci([r.recall[3] for r in results]),
        "recall@5": ci([r.recall[5] for r in results]),
        "recall@10": ci([r.recall[10] for r in results]),
        "mrr": ci([r.mrr for r in results]),
        "ndcg@10": ci([r.ndcg10 for r in results]),
        "latency_ms_p50": percentile(lat, 0.5),
        "latency_ms_p95": percentile(lat, 0.95),
    }
    by_type: dict[str, list[QuestionResult]] = defaultdict(list)
    for r in results:
        by_type[r.type].append(r)
    summary["by_type"] = {t: {"n": len(rs), "recall@10": ci([r.recall[10] for r in rs]),
                              "mrr": ci([r.mrr for r in rs])} for t, rs in sorted(by_type.items())}
    return summary


def build_searches(tenant: str, configs: Sequence[str]) -> dict[str, Search]:
    """Retrieval configurations of the ablation. All share the same pinned models and index."""
    from cortex.retrieval.base import Candidate
    from cortex.retrieval.fusion import rrf
    from cortex.retrieval.pipeline import build_retriever

    fetch = chunk_lookup(tenant)
    searches: dict[str, Search] = {}

    def wrap(fn: Callable[[str], list[Candidate]]) -> Search:
        return lambda q: fetch([c.chunk_id for c in fn(q)])

    for mode in ("dense", "sparse", "fused", "reranked"):
        if mode in configs:
            r = build_retriever(mode)  # type: ignore[arg-type]
            searches[mode] = wrap(lambda q, r=r: r.search(tenant, q, 10))
    if "graph" in configs or "reranked+graph" in configs:
        from cortex.graph.retrieve import GraphRetriever

        graph = GraphRetriever()
        if "graph" in configs:
            searches["graph"] = wrap(lambda q: graph.search_paths(tenant, q).candidates(10))
        if "reranked+graph" in configs:
            hybrid = build_retriever("reranked")

            def both(q: str) -> list[Candidate]:
                return rrf([graph.search_paths(tenant, q).candidates(10), hybrid.search(tenant, q, 10)], limit=10)

            searches["reranked+graph"] = wrap(both)
    return searches


# --------------------------------------------------------------------------------------------------- answers
@dataclass
class AnswerResult:
    id: str
    type: str
    question: str
    answer: str
    route: str
    not_found: bool
    partial: bool
    stop_reason: str | None
    evidence_recall: float  # share of labelled evidence present in the evidence shown to the model
    cited_support: float  # share of cited passages that satisfy some labelled evidence item
    citations: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    adversarial_pass: bool | None = None
    adversarial_notes: list[str] = field(default_factory=list)
    code: str | None = None
    judge: dict[str, Any] | None = None


def run_answers(tenant: str, questions: Sequence[Question], *, router: str = "llm",
                on_progress: Callable[[int, int, AnswerResult], None] | None = None) -> list[AnswerResult]:
    from cortex.answering import answer_question
    from cortex.security.prompting import cited_indices

    out: list[AnswerResult] = []
    for i, q in enumerate(questions, start=1):
        res = answer_question(tenant, q.question, router=router, log_calls=True)
        ev = res["evidence"]
        shown = [RetrievedChunk(e["chunk_id"], _doc_of(tenant, e["document_id"]), e["text"]) for e in ev]
        covered: set[int] = set()
        for c in shown:
            covered |= satisfied(q.evidence, c)
        cited = [n for n in cited_indices(res["answer"]) if 1 <= n <= len(shown)]
        supported = sum(1 for n in cited if satisfied(q.evidence, shown[n - 1])) if q.evidence else 0
        r = AnswerResult(
            id=q.id, type=q.type, question=q.question, answer=res["answer"], route=res["route"],
            not_found=res["not_found"], partial=res["partial"], stop_reason=res["stop_reason"],
            evidence_recall=len(covered) / len(q.evidence) if q.evidence else 0.0,
            cited_support=supported / len(cited) if cited else 0.0, citations=len(cited),
            input_tokens=res["input_tokens"], output_tokens=res["output_tokens"], cost_usd=res["cost_usd"],
            latency_ms=res["latency_ms"], code=res.get("code"),
        )
        if q.type == "adversarial":
            notes = [f"answer contains {s!r}" for s in q.extra.get("must_not_contain", []) if s.lower() in r.answer.lower()]  # type: ignore[union-attr]
            code = (res.get("code") or "").lower()
            notes += [f"sandbox code contains {s!r}" for s in q.extra.get("sandbox_must_not_contain", [])  # type: ignore[union-attr]
                      if s.lower() in code]
            r.adversarial_pass, r.adversarial_notes = not notes, notes
        out.append(r)
        if on_progress:
            on_progress(i, len(questions), r)
    return out


_DOC_CACHE: dict[tuple[str, str], str] = {}


def _doc_of(tenant: str, document_id: str) -> str:
    key = (tenant, document_id)
    if key not in _DOC_CACHE:
        from cortex.db import repo
        from cortex.db.session import tenant_session

        with tenant_session(tenant) as db:
            d = repo.get_document(db, tenant, document_id)
        _DOC_CACHE[key] = d.filename if d else ""
    return _DOC_CACHE[key]


def summarise_answers(rs: Sequence[AnswerResult]) -> dict[str, Any]:
    def ci(values: list[float]) -> dict[str, float]:
        iv = bootstrap_ci(values)
        return {"value": iv.value, "low": iv.low, "high": iv.high}

    answerable = [r for r in rs if r.type in ("content", "relationship")]
    no_answer = [r for r in rs if r.type == "no_answer"]
    adversarial = [r for r in rs if r.type == "adversarial"]
    answered = [r for r in answerable if not r.not_found]
    out: dict[str, Any] = {
        "n": len(rs),
        "answered_rate": ci([0.0 if r.not_found else 1.0 for r in answerable]),
        "no_answer_accuracy": ci([1.0 if r.not_found else 0.0 for r in no_answer]),
        "evidence_recall": ci([r.evidence_recall for r in answerable]),
        "cited_support": ci([r.cited_support for r in answered]),
        "partial_rate": mean([1.0 if r.partial else 0.0 for r in rs]),
        "stop_reasons": dict(Counter(r.stop_reason for r in rs if r.stop_reason)),
        "routes": dict(Counter(r.route for r in rs)),
        "latency_ms_p50": percentile([float(r.latency_ms) for r in rs], 0.5),
        "latency_ms_p95": percentile([float(r.latency_ms) for r in rs], 0.95),
        "tokens_per_question": mean([float(r.input_tokens + r.output_tokens) for r in rs]),
        "notional_cost_per_question_usd": mean([r.cost_usd for r in rs]),
        "adversarial_pass_rate": mean([1.0 if r.adversarial_pass else 0.0 for r in adversarial]) if adversarial else None,
    }
    judged = [r for r in answered if r.judge]
    if judged:
        out["judge_correct"] = ci([1.0 if r.judge and r.judge.get("correctness") == "correct" else 0.0 for r in judged])
        out["judge_faithful"] = ci([1.0 if r.judge and r.judge.get("faithful") else 0.0 for r in judged])
    return out


# ------------------------------------------------------------------------------------------------------ judge
JUDGE_PROMPT_VERSION = "judge-v1"
JUDGE_SYSTEM = (
    "You grade answers from a document question-answering system. You get the question, a reference answer "
    "written by a human, the passages the system cited, and the system's answer.\n"
    "Grade two things independently:\n"
    "- correctness: 'correct' if the answer states the reference's key facts (extra correct detail is fine, length "
    "earns no credit), 'partial' if it states some of them, 'incorrect' otherwise.\n"
    "- faithful: true if every claim in the answer is supported by the cited passages, false otherwise.\n"
    'Reply with JSON only: {"correctness": "correct"|"partial"|"incorrect", "faithful": true|false, '
    '"reason": "<one sentence>"}'
)


def judge_answers(tenant: str, questions: Sequence[Question], results: Sequence[AnswerResult]) -> None:
    from pydantic import BaseModel

    from cortex.models.client import Message
    from cortex.models.llm import CallContext, get_llm

    class Verdict(BaseModel):
        correctness: str
        faithful: bool
        reason: str = ""

    llm = get_llm()
    ctx = CallContext(tenant_id=tenant, log_calls=True)
    by_id = {q.id: q for q in questions}
    for r in results:
        q = by_id[r.id]
        if r.not_found or not q.answerable:
            continue
        cited_text = "\n".join(f"- {e.quote}" for e in q.evidence)
        user = (f"Question: {q.question}\nReference answer: {q.reference}\nKey evidence: \n{cited_text}\n\n"
                f"System answer:\n{r.answer}")
        try:
            v = llm.complete_json(ctx, Verdict, step="judge", prompt_version=JUDGE_PROMPT_VERSION,
                                  messages=[Message("system", JUDGE_SYSTEM), Message("user", user)], max_tokens=200)
            r.judge = {"correctness": v.correctness, "faithful": v.faithful, "reason": v.reason}
        except Exception as exc:  # a failed judgement is recorded, not fatal
            r.judge = {"error": str(exc)[:200]}


# ----------------------------------------------------------------------------------------------------- router
def run_router(path: Path, router: Any) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    labels = ("content", "relationship", "both")
    matrix = {t: dict.fromkeys(labels, 0) for t in labels}
    t0 = time.perf_counter()
    correct = []
    for row in rows:
        pred = router.route(row["question"])
        matrix[row["route"]][pred] += 1
        correct.append(1.0 if pred == row["route"] else 0.0)
    elapsed = (time.perf_counter() - t0) * 1000 / max(1, len(rows))
    acc = bootstrap_ci(correct)
    return {"router": router.name, "n": len(rows), "accuracy": {"value": acc.value, "low": acc.low, "high": acc.high},
            "confusion": matrix, "ms_per_query": elapsed}


# ---------------------------------------------------------------------------------------------------- reports
def write_report(name: str, payload: dict[str, Any], markdown: str) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    payload = {"name": name, "created_at": stamp, "git_commit": git_commit(), **payload}
    (REPORTS / f"{stamp}-{name}.json").write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    md_path = REPORTS / f"{stamp}-{name}.md"
    md_path.write_text(markdown, encoding="utf-8")
    try:
        _record_run(name, payload)
    except Exception as exc:  # the database is optional for offline runs (e.g. a Kaggle notebook)
        print(f"note: eval run not recorded in the database: {exc}")
    return md_path


def _json_default(o: Any) -> Any:
    if hasattr(o, "__dataclass_fields__"):
        return asdict(o)
    if isinstance(o, Interval):
        return {"value": o.value, "low": o.low, "high": o.high}
    raise TypeError(type(o))


def _record_run(name: str, payload: dict[str, Any]) -> None:
    from sqlalchemy import text

    from cortex.db.session import get_engine

    metrics = payload.get("summary") or payload.get("configs") or {}
    with get_engine().begin() as c:
        c.execute(text("INSERT INTO eval_runs (name, git_commit, config, metrics, report_path) VALUES (:n, :g,"
                       " CAST(:c AS jsonb), CAST(:m AS jsonb), :p)"),
                  {"n": name, "g": payload.get("git_commit"), "c": json.dumps(payload.get("config", {})),
                   "m": json.dumps(metrics, default=_json_default), "p": f"eval/reports/{payload['created_at']}-{name}.md"})


def previous_report(name: str) -> dict[str, Any] | None:
    files = sorted(REPORTS.glob(f"*-{name}.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def regression_check(prev: dict[str, Any] | None, current: dict[str, list[QuestionResult]], config: str,
                     metric_k: int = 10) -> tuple[bool, str]:
    """Fail only on a statistically significant drop (paired over the same questions), not on every wobble."""
    if not prev or config not in prev.get("per_question", {}):
        return False, "no previous report to compare with"
    before = {r["id"]: r["recall"][str(metric_k)] for r in prev["per_question"][config]}
    now = {r.id: r.recall[metric_k] for r in current[config]}
    ids = sorted(set(before) & set(now))
    if len(ids) < 5:
        return False, "too few shared questions to compare"
    res = paired_compare([before[i] for i in ids], [now[i] for i in ids])
    regressed = res.significant and res.mean_diff < 0
    return regressed, f"{config} recall@{metric_k} vs previous report: {res.fmt()}"
