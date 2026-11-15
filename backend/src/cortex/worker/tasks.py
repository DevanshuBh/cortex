"""Celery tasks. Each one is safe to run twice: redelivery after a crash must not duplicate side effects.

- ingest: replaces the document's chunks in one transaction (deterministic chunk ids).
- extract: MERGE-based graph writes are idempotent; stale chunk facts are removed first.
- ask: the answer row is unique per task id; agent side effects go through the tool_effects ledger.
- delete: deleting what is already gone is a no-op.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import redis
from celery.exceptions import SoftTimeLimitExceeded

from cortex import storage
from cortex.answering import TaskCancelled, answer_question
from cortex.config import get_settings
from cortex.db import repo
from cortex.db.session import tenant_session
from cortex.models.client import ModelError
from cortex.observability import metrics
from cortex.observability.tracing import span
from cortex.streaming import EventSink
from cortex.worker.app import app

log = logging.getLogger(__name__)
s = get_settings()

_redis = redis.Redis.from_url(s.redis_url, decode_responses=True)


def cancel_key(task_id: str) -> str:
    return f"task:{task_id}:cancel"


def _start(tenant_id: str, task_id: str) -> repo.TaskRow | None:
    with tenant_session(tenant_id) as db:
        return repo.start_task(db, tenant_id, task_id)


def _finish(
    tenant_id: str,
    task_id: str,
    status: str,
    kind: str,
    started: float,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with tenant_session(tenant_id) as db:
        repo.finish_task(db, tenant_id, task_id, status, result=result, error=error)
    metrics.TASKS.labels(kind=kind, status=status).inc()
    metrics.TASK_DURATION.labels(kind=kind).observe(time.monotonic() - started)


# ------------------------------------------------------------------------------------------------------ ingest
@app.task(
    name="cortex.ingest",
    soft_time_limit=s.ingest_soft_time_limit,
    time_limit=s.ingest_time_limit,
    autoretry_for=(ConnectionError,),
    retry_backoff=True,
    max_retries=3,
)
def ingest_task(tenant_id: str, task_id: str, document_id: str, extract_graph: bool = True) -> None:
    from cortex.ingest.service import ingest_document

    started = time.monotonic()
    if _start(tenant_id, task_id) is None:
        return  # already finished: a redelivered copy
    sink = EventSink(task_id)
    try:
        with span("task.ingest", tenant=tenant_id, document_id=document_id):
            result = ingest_document(tenant_id, document_id, progress=sink.emit)
        if result.status == "failed":
            _finish(tenant_id, task_id, "failed", "ingest", started, error=result.error)
            sink.emit("error", {"message": result.error})
            return
        payload = {
            "document_id": document_id,
            "chunks": len(result.chunk_ids),
            "reused_embeddings": result.reused_embeddings,
        }
        _finish(tenant_id, task_id, "succeeded", "ingest", started, result=payload)
        sink.emit("done", payload)
        if extract_graph:
            enqueue_extract(tenant_id, document_id)
    except SoftTimeLimitExceeded:
        _fail_document(tenant_id, document_id, "ingestion timed out")
        _finish(tenant_id, task_id, "failed", "ingest", started, error="time limit")
        sink.emit("error", {"message": "ingestion timed out"})
    except LookupError as exc:
        _finish(tenant_id, task_id, "failed", "ingest", started, error=str(exc))
        sink.emit("error", {"message": str(exc)})


def _fail_document(tenant_id: str, document_id: str, error: str) -> None:
    with tenant_session(tenant_id) as db:
        repo.set_document_status(db, tenant_id, document_id, "failed", error=error)


def enqueue_extract(tenant_id: str, document_id: str) -> str:
    with tenant_session(tenant_id) as db:
        task_id, created = repo.create_task(
            db,
            tenant_id,
            "extract",
            {"document_id": document_id},
            idempotency_key=f"extract:{document_id}:{time.time_ns()}",
        )
    if created:
        extract_task.delay(tenant_id, task_id, document_id)
    return task_id


# ----------------------------------------------------------------------------------------------------- extract
@app.task(name="cortex.extract", soft_time_limit=s.extract_soft_time_limit, time_limit=s.extract_time_limit)
def extract_task(tenant_id: str, task_id: str, document_id: str) -> None:
    from sqlalchemy import text

    from cortex.graph.extract import extract_into_graph
    from cortex.graph.store import GraphStore
    from cortex.models.llm import CallContext, get_llm

    started = time.monotonic()
    if _start(tenant_id, task_id) is None:
        return
    sink = EventSink(task_id)
    with tenant_session(tenant_id) as db:
        doc = repo.get_document(db, tenant_id, document_id)
        chunks = [
            (r[0], r[1], r[2])
            for r in db.execute(
                text(
                    "SELECT id::text, heading_path, text FROM chunks WHERE tenant_id = :t AND document_id = CAST(:d"
                    " AS uuid) ORDER BY position"
                ),
                {"t": tenant_id, "d": document_id},
            )
        ]
        confidential = repo.tenant_is_confidential(db, tenant_id)
        if doc is not None:
            repo.set_document_status(db, tenant_id, document_id, "extracting")
    if doc is None:
        _finish(tenant_id, task_id, "failed", "extract", started, error="document not found")
        return
    ctx = CallContext(tenant_id=tenant_id, task_id=task_id, confidential=confidential)
    try:
        stats = extract_into_graph(
            get_llm(),
            ctx,
            GraphStore(),
            document_id,
            chunks,
            on_progress=lambda i, n: sink.emit("progress", {"done": i, "total": n}),
        )
        payload = {
            "chunks": stats.chunks,
            "failed": stats.failed,
            "failure_rate": round(stats.failure_rate, 4),
            "entities": stats.entities,
            "relations": stats.relations,
            "tokens": ctx.usage.total_tokens,
        }
        _finish(tenant_id, task_id, "succeeded", "extract", started, result=payload)
        sink.emit("done", payload)
    except (SoftTimeLimitExceeded, ModelError) as exc:
        _finish(tenant_id, task_id, "failed", "extract", started, error=str(exc)[:500])
        sink.emit("error", {"message": "graph extraction failed; passages remain searchable"})
    finally:
        with tenant_session(tenant_id) as db:
            if repo.get_document(db, tenant_id, document_id) is not None:
                repo.set_document_status(db, tenant_id, document_id, "ready")


# --------------------------------------------------------------------------------------------------------- ask
@app.task(
    name="cortex.ask",
    bind=True,
    soft_time_limit=s.ask_soft_time_limit,
    time_limit=s.ask_time_limit,
    max_retries=1,
)
def ask_task(self: Any, tenant_id: str, task_id: str) -> None:
    started = time.monotonic()
    task = _start(tenant_id, task_id)
    if task is None:
        return
    sink = EventSink(task_id)
    with tenant_session(tenant_id) as db:
        existing = repo.get_answer(db, tenant_id, task_id)
    if existing is not None:  # crashed after saving, before finishing: finish without re-answering
        _finish(tenant_id, task_id, "succeeded", "ask", started, result={"replayed": True})
        sink.emit("done", {"task_id": task_id})
        return
    question = str(task.input.get("question", ""))
    sink.emit("status", {"status": "running", "attempt": task.attempts})
    try:
        result = answer_question(
            tenant_id,
            question,
            task_id=task_id,
            emit=sink.emit,
            on_token=sink.token,
            router=str(task.input.get("router") or "llm"),
            cancelled=lambda: bool(_redis.exists(cancel_key(task_id))),
        )
        sink.flush()
        with tenant_session(tenant_id) as db:
            repo.save_answer(db, tenant_id, task_id, result)
        summary = {
            k: result[k]
            for k in (
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
        _finish(tenant_id, task_id, "succeeded", "ask", started, result=summary)
        sink.emit(
            "answer",
            {
                "answer": result["answer"],
                "evidence": result["evidence"],
                "graph_paths": result["graph_paths"],
                **summary,
            },
        )
        sink.emit("done", {"task_id": task_id})
    except TaskCancelled:
        _finish(tenant_id, task_id, "cancelled", "ask", started, error="cancelled by user")
        sink.emit("cancelled", {"task_id": task_id})
    except SoftTimeLimitExceeded:
        _finish(tenant_id, task_id, "failed", "ask", started, error="time limit")
        sink.emit("error", {"message": "The answer took too long and was stopped."})
    except ModelError as exc:
        if exc.throttled and self.request.retries < self.max_retries:
            sink.emit("status", {"status": "retrying", "reason": "model throttled"})
            raise self.retry(countdown=5) from exc
        _finish(tenant_id, task_id, "failed", "ask", started, error=str(exc)[:500])
        sink.emit("error", {"message": "The language model is unavailable. Please try again."})
    except Exception as exc:
        log.exception("ask task %s failed", task_id)
        _finish(tenant_id, task_id, "failed", "ask", started, error=f"{type(exc).__name__}: {exc}"[:500])
        sink.emit("error", {"message": "Something went wrong while answering. Please try again."})


# ------------------------------------------------------------------------------------------------------ delete
@app.task(name="cortex.delete_document", max_retries=3, autoretry_for=(ConnectionError,), retry_backoff=True)
def delete_document_task(tenant_id: str, task_id: str, document_id: str, object_key: str, actor: str) -> None:
    """True deletion: chunks and vectors, graph facts only this document supported, and the stored object."""
    from cortex.graph.store import GraphStore

    started = time.monotonic()
    if _start(tenant_id, task_id) is None:
        return
    with tenant_session(tenant_id) as db:
        chunk_ids = repo.delete_document_rows(db, tenant_id, document_id)
        repo.audit(db, tenant_id, actor, "document.delete", document_id, {"chunks": len(chunk_ids)})
    store = GraphStore()
    graph_ids = store.chunk_ids_for_document(tenant_id, document_id)
    store.delete_chunks(tenant_id, sorted(set(chunk_ids) | graph_ids))
    storage.delete(object_key)
    _finish(tenant_id, task_id, "succeeded", "delete", started, result={"chunks": len(chunk_ids)})
    EventSink(task_id).emit("done", {"document_id": document_id})
