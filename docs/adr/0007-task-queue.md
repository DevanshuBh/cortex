# ADR 0007 — Celery on a non-cluster Redis broker; Redis Streams for progress

Status: accepted · 2026-11-14

## Decision
- Celery with `acks_late`, `task_reject_on_worker_lost`, `worker_prefetch_multiplier = 1`, soft and hard time limits
  per task type, separate `ask` and `ingest` queues.
- Broker: Redis (non-cluster mode, which Celery's Redis transport requires). `visibility_timeout` = 3,600 s, above
  the longest hard limit (2,500 s) — checked at worker start, because a shorter one redelivers running tasks.
  `visibility_timeout` exists only for the Redis and SQS brokers.
- Progress and tokens: one Redis Stream per task (`XADD`, capped, 1 h TTL), read with `XREAD`, sent as SSE whose
  event id is the stream id. Pub/Sub was rejected: it drops whatever is published while the browser reconnects
  (`tests/integration/test_streaming.py` demonstrates the loss).

## Alternatives
SQS (managed, but no local free equivalent with identical semantics); a workflow engine such as Temporal (durable,
heavier to run on a free VM). Agent durability comes from Postgres checkpoints instead (staff step S.5).
