"""Repositories. Every function takes the tenant explicitly and every query filters on it (isolation layer 1);
row-level security underneath is layer 2. Sessions come from ``tenant_session``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from cortex.db.session import tenant_session
from cortex.ingest.chunk import Chunk


def vec_literal(v: np.ndarray | Sequence[float]) -> str:
    return "[" + ",".join(f"{float(x):.7g}" for x in v) + "]"


# ---------------------------------------------------------------------------------------------------- tenants
def ensure_tenant(tenant_id: str, name: str | None = None, confidential: bool = False) -> None:
    with tenant_session(tenant_id) as db:
        db.execute(
            text(
                "INSERT INTO tenants (id, name, confidential) VALUES (:t, :n, :c) ON CONFLICT (id) DO UPDATE"
                " SET confidential = EXCLUDED.confidential"
            ),
            {"t": tenant_id, "n": name or tenant_id, "c": confidential},
        )


def tenant_is_confidential(db: Session, tenant_id: str) -> bool:
    row = db.execute(text("SELECT confidential FROM tenants WHERE id = :t"), {"t": tenant_id}).first()
    return bool(row and row[0])


# -------------------------------------------------------------------------------------------------- documents
@dataclass(frozen=True, slots=True)
class DocumentRow:
    id: str
    tenant_id: str
    title: str
    filename: str
    mime: str
    object_key: str
    size_bytes: int | None
    status: str
    error: str | None
    chunk_count: int
    content_hash: str | None
    created_at: datetime
    updated_at: datetime


_DOC_COLS = (
    "id::text, tenant_id, title, filename, mime, object_key, size_bytes, status, error, chunk_count,"
    " content_hash, created_at, updated_at"
)


def create_document(
    db: Session,
    tenant_id: str,
    *,
    title: str,
    filename: str,
    mime: str,
    object_key: str,
    status: str,
    document_id: str | None = None,
    size_bytes: int | None = None,
) -> str:
    doc_id = document_id or str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO documents (tenant_id, id, title, filename, mime, object_key, status, size_bytes)"
            " VALUES (:t, :id, :title, :fn, :mime, :key, :status, :size)"
        ),
        {
            "t": tenant_id,
            "id": doc_id,
            "title": title,
            "fn": filename,
            "mime": mime,
            "key": object_key,
            "status": status,
            "size": size_bytes,
        },
    )
    return doc_id


def get_document(db: Session, tenant_id: str, document_id: str) -> DocumentRow | None:
    row = db.execute(
        text(f"SELECT {_DOC_COLS} FROM documents WHERE tenant_id = :t AND id = CAST(:id AS uuid)"),  # noqa: S608 - constant column list
        {"t": tenant_id, "id": document_id},
    ).first()
    return DocumentRow(*row) if row else None


def list_documents(
    db: Session, tenant_id: str, *, query: str | None, limit: int, offset: int
) -> list[DocumentRow]:
    sql = f"SELECT {_DOC_COLS} FROM documents WHERE tenant_id = :t"  # noqa: S608 - constant column list
    params: dict[str, Any] = {"t": tenant_id, "limit": limit, "offset": offset}
    if query:
        sql += " AND title ILIKE :q"
        params["q"] = f"%{query.replace('%', '').replace('_', '')}%"
    sql += " ORDER BY created_at DESC, id LIMIT :limit OFFSET :offset"
    return [DocumentRow(*r) for r in db.execute(text(sql), params)]


def count_documents(db: Session, tenant_id: str) -> int:
    return int(
        db.execute(text("SELECT count(*) FROM documents WHERE tenant_id = :t"), {"t": tenant_id}).scalar_one()
    )


def set_document_status(
    db: Session,
    tenant_id: str,
    document_id: str,
    status: str,
    *,
    error: str | None = None,
    title: str | None = None,
    content_hash: str | None = None,
    chunk_count: int | None = None,
    chunking_version: str | None = None,
    size_bytes: int | None = None,
) -> None:
    db.execute(
        text(
            "UPDATE documents SET status = :s, error = :e, title = COALESCE(:title, title),"
            " content_hash = COALESCE(:h, content_hash), chunk_count = COALESCE(:cc, chunk_count),"
            " chunking_version = COALESCE(:cv, chunking_version), size_bytes = COALESCE(:size, size_bytes),"
            " updated_at = now() WHERE tenant_id = :t AND id = CAST(:id AS uuid)"
        ),
        {
            "s": status,
            "e": error,
            "title": title,
            "h": content_hash,
            "cc": chunk_count,
            "cv": chunking_version,
            "size": size_bytes,
            "t": tenant_id,
            "id": document_id,
        },
    )


def delete_document_rows(db: Session, tenant_id: str, document_id: str) -> list[str]:
    """Delete a document and its chunks; returns the deleted chunk ids (for graph and cache cleanup)."""
    chunk_ids = [
        r[0]
        for r in db.execute(
            text("SELECT id::text FROM chunks WHERE tenant_id = :t AND document_id = CAST(:d AS uuid)"),
            {"t": tenant_id, "d": document_id},
        )
    ]
    db.execute(
        text("DELETE FROM documents WHERE tenant_id = :t AND id = CAST(:d AS uuid)"),
        {"t": tenant_id, "d": document_id},
    )
    return chunk_ids


def audit(db: Session, tenant_id: str, actor: str, action: str, target: str, detail: dict[str, Any]) -> None:
    db.execute(
        text(
            "INSERT INTO audit_log (tenant_id, actor, action, target, detail)"
            " VALUES (:t, :a, :act, :tg, CAST(:d AS jsonb))"
        ),
        {"t": tenant_id, "a": actor, "act": action, "tg": target, "d": json.dumps(detail)},
    )


# ----------------------------------------------------------------------------------------------------- chunks
def embeddings_by_hash(db: Session, tenant_id: str, document_id: str) -> dict[str, str]:
    """Existing embeddings of a document keyed by content hash, so re-ingestion re-embeds only changed chunks."""
    rows = db.execute(
        text(
            "SELECT content_hash, embedding::text FROM chunks WHERE tenant_id = :t AND document_id = CAST(:d AS"
            " uuid) AND embedding IS NOT NULL"
        ),
        {"t": tenant_id, "d": document_id},
    )
    return {h: e for h, e in rows}


def replace_chunks(
    db: Session,
    tenant_id: str,
    document_id: str,
    chunking_version: str,
    chunks: Sequence[Chunk],
    embeddings: Sequence[str],
) -> list[str]:
    """Idempotent: a redelivered ingestion task replaces the document's chunks instead of duplicating them."""
    db.execute(
        text("DELETE FROM chunks WHERE tenant_id = :t AND document_id = CAST(:d AS uuid)"),
        {"t": tenant_id, "d": document_id},
    )
    ids: list[str] = []
    rows = []
    for c, e in zip(chunks, embeddings, strict=True):
        cid = str(uuid.uuid5(uuid.UUID(document_id), f"{chunking_version}:{c.position}:{c.content_hash}"))
        ids.append(cid)
        rows.append(
            {
                "t": tenant_id,
                "id": cid,
                "d": document_id,
                "pos": c.position,
                "hp": c.heading_path,
                "txt": c.text,
                "cs": c.char_start,
                "ce": c.char_end,
                "tok": c.token_count,
                "h": c.content_hash,
                "cv": chunking_version,
                "e": e,
            }
        )
    if rows:
        db.execute(
            text(
                "INSERT INTO chunks (tenant_id, id, document_id, position, heading_path, text, char_start, char_end,"
                " token_count, content_hash, chunking_version, embedding) VALUES (:t, CAST(:id AS uuid),"
                " CAST(:d AS uuid), :pos, :hp, :txt, :cs, :ce, :tok, :h, :cv, CAST(:e AS vector))"
            ),
            rows,
        )
    return ids


@dataclass(frozen=True, slots=True)
class ChunkRow:
    id: str
    document_id: str
    document_title: str
    position: int
    heading_path: str
    text: str
    char_start: int
    char_end: int
    filename: str
    mime: str


def get_chunks(db: Session, tenant_id: str, chunk_ids: Sequence[str]) -> list[ChunkRow]:
    if not chunk_ids:
        return []
    rows = db.execute(
        text(
            "SELECT c.id::text, c.document_id::text, d.title, c.position, c.heading_path, c.text, c.char_start,"
            " c.char_end, d.filename, d.mime FROM chunks c JOIN documents d ON d.id = c.document_id AND"
            " d.tenant_id = c.tenant_id WHERE c.tenant_id = :t AND c.id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"t": tenant_id, "ids": list(chunk_ids)},
    )
    by_id = {r[0]: ChunkRow(*r) for r in rows}
    return [by_id[i] for i in chunk_ids if i in by_id]


# ------------------------------------------------------------------------------------------------------ tasks
@dataclass(frozen=True, slots=True)
class TaskRow:
    id: str
    tenant_id: str
    kind: str
    status: str
    input: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


_TASK_COLS = (
    "id::text, tenant_id, kind, status, input, result, error, attempts, created_at, started_at, finished_at"
)


def create_task(
    db: Session,
    tenant_id: str,
    kind: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    created_by: str | None = None,
) -> tuple[str, bool]:
    """Returns (task_id, created). With an idempotency key, a retried request returns the original task."""
    task_id = str(uuid.uuid4())
    row = db.execute(
        text(
            "INSERT INTO tasks (tenant_id, id, kind, status, idempotency_key, input, created_by) VALUES (:t,"
            " CAST(:id AS uuid), :k, 'queued', :ik, CAST(:in AS jsonb), :by) ON CONFLICT (tenant_id, kind,"
            " idempotency_key) DO NOTHING RETURNING id::text"
        ),
        {
            "t": tenant_id,
            "id": task_id,
            "k": kind,
            "ik": idempotency_key,
            "in": json.dumps(payload),
            "by": created_by,
        },
    ).first()
    if row:
        return row[0], True
    existing = db.execute(
        text("SELECT id::text FROM tasks WHERE tenant_id = :t AND kind = :k AND idempotency_key = :ik"),
        {"t": tenant_id, "k": kind, "ik": idempotency_key},
    ).scalar_one()
    return str(existing), False


def get_task(db: Session, tenant_id: str, task_id: str) -> TaskRow | None:
    row = db.execute(
        text(f"SELECT {_TASK_COLS} FROM tasks WHERE tenant_id = :t AND id = CAST(:id AS uuid)"),  # noqa: S608 - constant column list
        {"t": tenant_id, "id": task_id},
    ).first()
    return TaskRow(*row) if row else None


def start_task(db: Session, tenant_id: str, task_id: str) -> TaskRow | None:
    """Mark running and count the attempt. Returns None if the task is already finished (skip redelivery)."""
    row = db.execute(
        text(
            "UPDATE tasks SET status = 'running', attempts = attempts + 1, started_at = COALESCE(started_at, now())"  # noqa: S608 - constant column list
            f" WHERE tenant_id = :t AND id = CAST(:id AS uuid) AND status IN ('queued', 'running') RETURNING"
            f" {_TASK_COLS}"
        ),
        {"t": tenant_id, "id": task_id},
    ).first()
    return TaskRow(*row) if row else None


def finish_task(
    db: Session,
    tenant_id: str,
    task_id: str,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    db.execute(
        text(
            "UPDATE tasks SET status = :s, result = CAST(:r AS jsonb), error = :e, finished_at = now()"
            " WHERE tenant_id = :t AND id = CAST(:id AS uuid) AND status NOT IN ('succeeded', 'cancelled')"
        ),
        {
            "s": status,
            "r": json.dumps(result) if result is not None else None,
            "e": error,
            "t": tenant_id,
            "id": task_id,
        },
    )


def task_status(db: Session, tenant_id: str, task_id: str) -> str | None:
    return db.execute(
        text("SELECT status FROM tasks WHERE tenant_id = :t AND id = CAST(:id AS uuid)"),
        {"t": tenant_id, "id": task_id},
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------------------------------- answers
def save_answer(db: Session, tenant_id: str, task_id: str, a: dict[str, Any]) -> bool:
    """At most one answer per task: a redelivered task cannot write a second one."""
    row = db.execute(
        text(
            "INSERT INTO answers (tenant_id, task_id, question, answer, evidence, route, partial, not_found, steps,"
            " input_tokens, output_tokens, cost_usd, latency_ms, trace, graph_paths) VALUES (:t, CAST(:id AS uuid),"
            " :q, :a, CAST(:ev AS jsonb), :route, :partial, :nf, :steps, :it, :ot, :cost, :lat,"
            " CAST(:trace AS jsonb), CAST(:gp AS jsonb))"
            " ON CONFLICT (task_id) DO NOTHING RETURNING task_id"
        ),
        {
            "t": tenant_id,
            "id": task_id,
            "q": a["question"],
            "a": a["answer"],
            "ev": json.dumps(a["evidence"]),
            "route": a["route"],
            "partial": a["partial"],
            "nf": a["not_found"],
            "steps": a["steps"],
            "it": a["input_tokens"],
            "ot": a["output_tokens"],
            "cost": a["cost_usd"],
            "lat": a["latency_ms"],
            "trace": json.dumps(a.get("trace", [])),
            "gp": json.dumps(a.get("graph_paths", [])),
        },
    ).first()
    return row is not None


def get_answer(db: Session, tenant_id: str, task_id: str) -> dict[str, Any] | None:
    row = (
        db.execute(
            text(
                "SELECT question, answer, evidence, route, partial, not_found, steps, input_tokens, output_tokens,"
                " cost_usd, latency_ms, trace, graph_paths, created_at FROM answers WHERE tenant_id = :t AND task_id = CAST(:id AS"
                " uuid)"
            ),
            {"t": tenant_id, "id": task_id},
        )
        .mappings()
        .first()
    )
    if not row:
        return None
    out = dict(row)
    out["cost_usd"] = float(out["cost_usd"])
    return out


def upsert_feedback(
    db: Session, tenant_id: str, task_id: str, user_id: str, rating: int, comment: str | None
) -> None:
    db.execute(
        text(
            "INSERT INTO feedback (tenant_id, task_id, user_id, rating, comment) VALUES (:t, CAST(:id AS uuid), :u,"
            " :r, :c) ON CONFLICT (task_id, user_id) DO UPDATE SET rating = EXCLUDED.rating, comment ="
            " EXCLUDED.comment, created_at = now()"
        ),
        {"t": tenant_id, "id": task_id, "u": user_id, "r": rating, "c": comment},
    )


def usage_summary(db: Session, tenant_id: str, days: int) -> dict[str, Any]:
    params = {"t": tenant_id, "days": days}
    by_tier = db.execute(
        text(
            "SELECT tier, provider, count(*), sum(input_tokens), sum(output_tokens), sum(cost_usd),"
            " count(*) FILTER (WHERE NOT ok) FROM llm_calls WHERE tenant_id = :t AND created_at > now() -"
            " make_interval(days => :days) GROUP BY tier, provider ORDER BY tier"
        ),
        params,
    ).all()
    daily = db.execute(
        text(
            "SELECT date_trunc('day', created_at)::date, count(*), avg(cost_usd), avg(latency_ms),"
            " count(*) FILTER (WHERE not_found), count(*) FILTER (WHERE partial) FROM answers WHERE tenant_id = :t"
            " AND created_at > now() - make_interval(days => :days) GROUP BY 1 ORDER BY 1"
        ),
        params,
    ).all()
    routes = db.execute(
        text(
            "SELECT route, count(*), avg(cost_usd) FROM answers WHERE tenant_id = :t AND created_at > now() -"
            " make_interval(days => :days) GROUP BY route"
        ),
        params,
    ).all()
    fb = db.execute(
        text(
            "SELECT date_trunc('day', created_at)::date, count(*) FILTER (WHERE rating = 1), count(*) FILTER"
            " (WHERE rating = -1) FROM feedback WHERE tenant_id = :t AND created_at > now() - make_interval(days"
            " => :days) GROUP BY 1 ORDER BY 1"
        ),
        params,
    ).all()
    return {
        "by_tier": [
            {
                "tier": r[0],
                "provider": r[1],
                "calls": r[2],
                "input_tokens": int(r[3] or 0),
                "output_tokens": int(r[4] or 0),
                "cost_usd": float(r[5] or 0),
                "errors": r[6],
            }
            for r in by_tier
        ],
        "daily": [
            {
                "day": r[0].isoformat(),
                "answers": r[1],
                "avg_cost_usd": float(r[2] or 0),
                "avg_latency_ms": float(r[3] or 0),
                "not_found": r[4],
                "partial": r[5],
            }
            for r in daily
        ],
        "routes": [{"route": r[0], "answers": r[1], "avg_cost_usd": float(r[2] or 0)} for r in routes],
        "feedback": [{"day": r[0].isoformat(), "up": r[1], "down": r[2]} for r in fb],
    }
