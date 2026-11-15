"""Evaluation CLI.

    python -m cortex_eval retrieval --tenant k8s-docs            # ablation: dense / sparse / fused / reranked / graph
    python -m cortex_eval answers   --tenant k8s-docs --judge    # full agent answers, grading, adversarial checks
    python -m cortex_eval router                                 # router accuracy + confusion matrices
    python -m cortex_eval grading-sheet REPORT.json              # sheet for human grading (guide step 2.7)
    python -m cortex_eval kappa REPORT.json HUMAN.csv            # judge vs human agreement with CI

Exit code 2 means a statistically significant regression against the previous report of the same name.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cortex_eval.labels import load_questions
from cortex_eval.metrics import Interval, kappa_ci, paired_compare

HERE = Path(__file__).resolve().parents[1]


def _iv(d: dict[str, float]) -> str:
    return Interval(d["value"], d["low"], d["high"]).fmt()


def cmd_retrieval(args: argparse.Namespace) -> int:
    from cortex_eval import harness

    questions = load_questions(HERE / "questions.jsonl")
    configs = args.configs.split(",")
    searches = harness.build_searches(args.tenant, configs)
    results = {name: harness.run_retrieval(questions, fn) for name, fn in searches.items()}
    summaries = {name: harness.summarise(rs) for name, rs in results.items()}
    lines = [f"# Retrieval evaluation — {args.name}", "",
             f"Tenant `{args.tenant}`, {summaries[configs[0]]['n']} answerable questions, k = 10. "
             "Values are % with 95 % bootstrap intervals (1,000 resamples of questions).", "",
             "| Config | Recall@1 | Recall@5 | Recall@10 | MRR | nDCG@10 | p50 ms | p95 ms |", "|---|---|---|---|---|---|---|---|"]
    for name, s in summaries.items():
        lines.append(f"| {name} | {_iv(s['recall@1'])} | {_iv(s['recall@5'])} | {_iv(s['recall@10'])} | "
                     f"{Interval(**s['mrr']).fmt(pct=False)} | {_iv(s['ndcg@10'])} | {s['latency_ms_p50']:.0f} | "
                     f"{s['latency_ms_p95']:.0f} |")
    lines += ["", "## By question type (Recall@10)", "", "| Config | " + " | ".join(
        sorted(next(iter(summaries.values()))["by_type"])) + " |", "|---|" + "---|" * len(next(iter(summaries.values()))["by_type"])]
    for name, s in summaries.items():
        lines.append(f"| {name} | " + " | ".join(_iv(v["recall@10"]) for _, v in sorted(s["by_type"].items())) + " |")
    baseline = configs[0]
    lines += ["", f"## Paired comparisons against `{baseline}` (Recall@10, same questions)", ""]
    for name, rs in results.items():
        if name == baseline:
            continue
        res = paired_compare([r.recall[10] for r in results[baseline]], [r.recall[10] for r in rs])
        verdict = "significant" if res.significant else "within noise"
        lines.append(f"- **{name}**: {res.fmt()} — {verdict}")
    for pair in (("fused", "reranked"), ("reranked", "reranked+graph")):
        if all(p in results for p in pair):
            res = paired_compare([r.recall[10] for r in results[pair[0]]], [r.recall[10] for r in results[pair[1]]])
            lines.append(f"- **{pair[1]} vs {pair[0]}**: {res.fmt()} — "
                         f"{'significant' if res.significant else 'within noise'}")
    rel = [q.id for q in questions if q.type == "relationship"]
    if "graph" in results or "reranked+graph" in results:
        lines += ["", "## Relationship subset (guide step 3.4)", ""]
        for name in ("reranked", "graph", "reranked+graph"):
            if name in results:
                sub = [r for r in results[name] if r.id in rel]
                lines.append(f"- {name}: Recall@10 {_iv(harness.summarise(sub)['recall@10'])} (n = {len(sub)})")
    prev = harness.previous_report(args.name)
    regressed, note = harness.regression_check(prev, results, args.check_config)
    lines += ["", "## Regression check", "", f"- {note}", f"- result: {'REGRESSION' if regressed else 'ok'}"]
    payload = {"config": {"tenant": args.tenant, "configs": configs}, "configs": summaries,
               "per_question": {k: [asdict(r) for r in v] for k, v in results.items()}}
    path = harness.write_report(args.name, payload, "\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nreport: {path}")
    return 2 if regressed else 0


def cmd_answers(args: argparse.Namespace) -> int:
    os.environ["CORTEX_ROUTING_POLICY"] = args.policy
    from cortex.config import get_settings

    get_settings.cache_clear()
    from cortex.models import llm as llm_mod

    llm_mod._default_llm.cache_clear()
    from cortex_eval import harness

    questions = load_questions(HERE / "questions.jsonl") + load_questions(HERE / "adversarial.jsonl")
    if args.only:
        questions = [q for q in questions if q.type in args.only.split(",")]
    if args.limit:
        questions = questions[: args.limit]

    def progress(i: int, n: int, r: Any) -> None:
        state = "NOT FOUND" if r.not_found else ("partial" if r.partial else "answered")
        print(f"  [{i}/{n}] {r.id} {state:9} {r.latency_ms / 1000:5.1f}s ev={r.evidence_recall:.2f}", flush=True)

    results = harness.run_answers(args.tenant, questions, router=args.router, on_progress=progress)
    if args.judge:
        harness.judge_answers(args.tenant, questions, results)
    s = harness.summarise_answers(results)
    lines = [f"# Answer evaluation — {args.name}", "", f"Tenant `{args.tenant}`, routing policy `{args.policy}`, "
             f"router `{args.router}`, {s['n']} questions. Intervals: 95 % bootstrap.", "",
             "| Metric | Value |", "|---|---|",
             f"| Answered (answerable questions) | {_iv(s['answered_rate'])} |",
             f"| \"Not found\" on no-answer questions | {_iv(s['no_answer_accuracy'])} |",
             f"| Labelled evidence shown to the model | {_iv(s['evidence_recall'])} |",
             f"| Cited passages that support the label | {_iv(s['cited_support'])} |"]
    if "judge_correct" in s:
        lines += [f"| Judge: correct | {_iv(s['judge_correct'])} |", f"| Judge: faithful | {_iv(s['judge_faithful'])} |"]
    if s["adversarial_pass_rate"] is not None:
        lines.append(f"| Adversarial pass rate | {s['adversarial_pass_rate'] * 100:.0f} % |")
    lines += [f"| Partial answers | {s['partial_rate'] * 100:.1f} % |",
              f"| Latency p50 / p95 | {s['latency_ms_p50'] / 1000:.1f} s / {s['latency_ms_p95'] / 1000:.1f} s |",
              f"| Tokens per question | {s['tokens_per_question']:.0f} |",
              f"| Notional cost per question | ${s['notional_cost_per_question_usd']:.5f} (reference prices; real cost $0) |",
              "", f"Routes: {s['routes']} · stop reasons: {s['stop_reasons']}", "", "## Per question", "",
              "| id | type | route | outcome | ev recall | cited support | judge | s |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        outcome = "not found" if r.not_found else ("partial" if r.partial else "answered")
        if r.adversarial_pass is not None:
            outcome += " ✓" if r.adversarial_pass else " ✗ " + "; ".join(r.adversarial_notes)
        j = (r.judge or {}).get("correctness", "") + ("" if not r.judge else (" / faithful" if r.judge.get("faithful") else " / unfaithful"))
        lines.append(f"| {r.id} | {r.type} | {r.route} | {outcome} | {r.evidence_recall:.2f} | {r.cited_support:.2f} | "
                     f"{j} | {r.latency_ms / 1000:.1f} |")
    payload = {"config": {"tenant": args.tenant, "policy": args.policy, "router": args.router}, "summary": s,
               "answers": [asdict(r) for r in results]}
    path = harness.write_report(args.name, payload, "\n".join(lines) + "\n")
    print("\n".join(lines[:20]))
    print(f"\nreport: {path}")
    return 0


def cmd_router(args: argparse.Namespace) -> int:
    from cortex.models.llm import CallContext, get_llm
    from cortex.router import LLMRouter, RuleRouter
    from cortex_eval import harness

    path = HERE / "router_queries.jsonl"
    rule = harness.run_router(path, RuleRouter())
    llm = harness.run_router(path, LLMRouter(get_llm(), CallContext(tenant_id=args.tenant, log_calls=False)))
    lines = [f"# Router evaluation — {args.name}", "", f"{rule['n']} labelled queries (eval/router_queries.jsonl).", "",
             "| Router | Accuracy | ms per query |", "|---|---|---|"]
    for r in (rule, llm):
        lines.append(f"| {r['router']} | {_iv(r['accuracy'])} | {r['ms_per_query']:.1f} |")
    for r in (rule, llm):
        lines += ["", f"### Confusion matrix — {r['router']} (rows: label, columns: predicted)", "",
                  "| | content | relationship | both |", "|---|---|---|---|"]
        for label, row in r["confusion"].items():
            lines.append(f"| {label} | {row['content']} | {row['relationship']} | {row['both']} |")
    path_md = harness.write_report(args.name, {"config": {}, "summary": {"rules": rule, "llm": llm}}, "\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nreport: {path_md}")
    return 0


def cmd_grading_sheet(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    out = Path(args.out or Path(args.report).with_suffix(".grading.csv"))
    qs = {q.id: q for q in load_questions(HERE / "questions.jsonl")}
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "question", "reference", "answer", "human_correctness", "human_faithful"])
        for a in report["answers"]:
            if a["id"] in qs and not a["not_found"]:
                w.writerow([a["id"], a["question"], qs[a["id"]].reference, a["answer"], "", ""])
    print(f"wrote {out} — fill human_correctness (correct/partial/incorrect) and human_faithful (yes/no)")
    return 0


def cmd_kappa(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    judge = {a["id"]: a.get("judge") or {} for a in report["answers"]}
    human, machine, h_f, m_f = [], [], [], []
    with Path(args.human).open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            j = judge.get(row["id"], {})
            if row["human_correctness"] and "correctness" in j:
                human.append(row["human_correctness"].strip().lower())
                machine.append(j["correctness"])
                h_f.append("yes" if row["human_faithful"].strip().lower() in ("yes", "y", "true", "1") else "no")
                m_f.append("yes" if j.get("faithful") else "no")
    if len(human) < 10:
        print(f"only {len(human)} graded rows; grade at least 50 for a meaningful kappa (guide step 2.7)")
        return 1
    kc, kf = kappa_ci(human, machine), kappa_ci(h_f, m_f)
    print(f"n = {len(human)}\ncorrectness kappa {kc.fmt(pct=False)}\nfaithfulness kappa {kf.fmt(pct=False)}")
    print("trust the judge on the full set only if both lower bounds clear the threshold you set in advance (0.6)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cortex_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("retrieval")
    r.add_argument("--tenant", default="k8s-docs")
    r.add_argument("--configs", default="dense,sparse,fused,reranked,graph,reranked+graph")
    r.add_argument("--name", default="retrieval")
    r.add_argument("--check-config", default="reranked")
    r.set_defaults(fn=cmd_retrieval)
    a = sub.add_parser("answers")
    a.add_argument("--tenant", default="k8s-docs")
    a.add_argument("--name", default="answers")
    a.add_argument("--policy", choices=["routed", "small-only", "large-only"], default="routed")
    a.add_argument("--router", choices=["llm", "rules"], default="rules")
    a.add_argument("--judge", action="store_true")
    a.add_argument("--only", help="comma-separated question types")
    a.add_argument("--limit", type=int)
    a.set_defaults(fn=cmd_answers)
    ro = sub.add_parser("router")
    ro.add_argument("--tenant", default="k8s-docs")
    ro.add_argument("--name", default="router")
    ro.set_defaults(fn=cmd_router)
    g = sub.add_parser("grading-sheet")
    g.add_argument("report")
    g.add_argument("--out")
    g.set_defaults(fn=cmd_grading_sheet)
    k = sub.add_parser("kappa")
    k.add_argument("report")
    k.add_argument("human")
    k.set_defaults(fn=cmd_kappa)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
