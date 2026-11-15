"""Prometheus metrics. The API exposes /metrics; the worker exposes them on its own port (CORTEX_METRICS_PORT)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

LLM_CALLS = Counter("cortex_llm_calls_total", "LLM calls", ["provider", "tier", "step"])
LLM_ERRORS = Counter("cortex_llm_errors_total", "Failed LLM calls", ["provider", "throttled"])
LLM_TOKENS = Counter("cortex_llm_tokens_total", "LLM tokens", ["tier", "kind"])
LLM_COST = Counter("cortex_llm_cost_usd_total", "Notional LLM cost in USD at reference prices", ["tier"])
LLM_LATENCY = Histogram(
    "cortex_llm_latency_seconds",
    "LLM call latency",
    ["tier"],
    buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128),
)
STRUCTURED_OUTPUT_FAILURES = Counter(
    "cortex_structured_output_failures_total", "Model output that failed schema validation", ["step"]
)

TASKS = Counter("cortex_tasks_total", "Finished tasks", ["kind", "status"])
TASK_DURATION = Histogram(
    "cortex_task_duration_seconds",
    "Task wall-clock time",
    ["kind"],
    buckets=(0.5, 1, 2, 5, 10, 20, 40, 80, 160, 320),
)
QUEUE_DEPTH = Gauge("cortex_queue_depth", "Messages waiting in a Celery queue", ["queue"])

RETRIEVAL_LATENCY = Histogram(
    "cortex_retrieval_latency_seconds",
    "Retrieval stage latency",
    ["stage"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
LOOP_GUARD = Counter("cortex_loop_guard_triggers_total", "Agent runs stopped by a guard", ["reason"])
ANSWERS = Counter("cortex_answers_total", "Answers produced", ["route", "outcome"])
QUERY_COST = Histogram(
    "cortex_query_cost_usd",
    "Notional cost per answered question",
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1),
)
INGEST_CHUNKS = Counter("cortex_ingest_chunks_total", "Chunks written by ingestion")
INGEST_TRUNCATION = Counter(
    "cortex_ingest_truncation_splits_total", "Pieces that exceeded the embedding token limit and were split"
)
EVAL_RECALL = Gauge("cortex_eval_recall_at_10", "Recall@10 of the latest evaluation run", ["config"])
SANDBOX_RUNS = Counter("cortex_sandbox_runs_total", "Sandbox executions", ["outcome"])
WEB_VITALS = Histogram(
    "cortex_web_vitals",
    "Real-user Core Web Vitals reported by browsers",
    ["name", "rating"],
    buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 2.5, 4, 8, 200, 500, 1000, 2500, 4000, 8000),
)
WEB_ERRORS = Counter("cortex_web_errors_total", "JavaScript errors reported by browsers")
