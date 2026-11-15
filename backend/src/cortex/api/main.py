"""CORTEX HTTP API (FastAPI). Slow work is queued to Celery; progress streams back over SSE."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import redis
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from cortex import storage
from cortex.api import schemas
from cortex.api.auth import AdminPrincipal, CurrentPrincipal
from cortex.config import get_settings
from cortex.db import repo
from cortex.db.session import get_engine, tenant_session
from cortex.ingest.parse import SUPPORTED_MIME, ParseError, mime_for
from cortex.observability import metrics
from cortex.observability.tracing import setup_tracing
from cortex.streaming import read_events

log = logging.getLogger(__name__)
settings = get_settings()
QUEUES = ("ask", "ingest")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    from cortex.logging_setup import configure_logging

    configure_logging()
    setup_tracing("api")
    yield


app = FastAPI(
    title="CORTEX API",
    version="1.0.0",
    description="Multi-tenant research assistant: cited answers over your documents.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
    expose_headers=["Location"],
    max_age=600,
)


# ------------------------------------------------------------------------------------------- problem details
def _problem(status_code: int, title: str, detail: str | None, request: Request) -> JSONResponse:
    body = schemas.Problem(title=title, status=status_code, detail=detail, instance=str(request.url.path))
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=status_code, media_type="application/problem+json"
    )


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    resp = _problem(exc.status_code, _TITLES.get(exc.status_code, "Error"), str(exc.detail), request)
    for k, v in (exc.headers or {}).items():
        resp.headers[k] = v
    return resp


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    resp = _problem(422, "Invalid request", "One or more fields are invalid.", request)
    body = json.loads(bytes(resp.body))
    body["errors"] = [
        {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()
    ]
    return JSONResponse(body, status_code=422, media_type="application/problem+json")


_TITLES = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    409: "Conflict",
    413: "Payload too large",
    415: "Unsupported media type",
    422: "Invalid request",
    503: "Unavailable",
}


# ----------------------------------------------------------------------------------------------- health/metrics
def _redis() -> redis.Redis:
    return redis.Redis.from_url(settings.broker_url, decode_responses=True, socket_timeout=2)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"
    try:
        _redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503
    )


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    try:
        r = _redis()
        for q in QUEUES:
            metrics.QUEUE_DEPTH.labels(queue=q).set(r.llen(q))
    except redis.RedisError:
        pass
    try:  # latest nightly evaluation, so "quality dropped below baseline" can alert like any other metric
        with get_engine().connect() as c:
            row = c.execute(
                text(
                    "SELECT metrics FROM eval_runs WHERE name = 'retrieval' ORDER BY created_at DESC LIMIT 1"
                )
            ).first()
        for cfg, m in (row[0] if row else {}).items():
            if isinstance(m, dict) and "recall@10" in m:
                metrics.EVAL_RECALL.labels(config=cfg).set(float(m["recall@10"]["value"]))
    except Exception:  # metrics must never fail the scrape
        log.debug("eval metric unavailable", exc_info=True)
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


# -------------------------------------------------------------------------------------------------------- me
@app.get("/v1/me", response_model=schemas.Me, tags=["auth"])
def me(p: CurrentPrincipal) -> schemas.Me:
    return schemas.Me(user_id=p.user_id, tenant_id=p.tenant_id, roles=sorted(p.roles))


# ------------------------------------------------------------------------------------------------- documents
def _doc_out(d: repo.DocumentRow) -> schemas.Document:
    return schemas.Document(
        id=d.id,
        title=d.title,
        filename=d.filename,
        mime=d.mime,
        size_bytes=d.size_bytes,
        status=d.status,
        error=d.error,
        chunk_count=d.chunk_count,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


def _check_upload(filename: str, content_type: str | None, size: int) -> str:
    if size > settings.max_upload_bytes:
        raise HTTPException(413, f"file is larger than {settings.max_upload_bytes // (1024 * 1024)} MB")
    try:
        return mime_for(filename, content_type)
    except ParseError as exc:
        raise HTTPException(415, f"{exc}. Supported: PDF, Markdown, HTML, plain text.") from exc


def _enqueue_ingest(tenant_id: str, document_id: str, actor: str) -> str:
    from cortex.worker.tasks import ingest_task

    with tenant_session(tenant_id) as db:
        task_id, created = repo.create_task(
            db,
            tenant_id,
            "ingest",
            {"document_id": document_id},
            idempotency_key=f"ingest:{document_id}",
            created_by=actor,
        )
    if created:
        ingest_task.delay(tenant_id, task_id, document_id)
    return task_id


@app.post("/v1/documents", response_model=schemas.CreateDocumentResponse, status_code=201, tags=["documents"])
def create_document(
    body: schemas.CreateDocumentRequest, p: CurrentPrincipal
) -> schemas.CreateDocumentResponse:
    """Register a document and get a presigned URL; the browser uploads straight to object storage."""
    mime = _check_upload(body.filename, body.content_type, body.size_bytes)
    doc_id = str(uuid.uuid4())
    key = storage.object_key(p.tenant_id, doc_id, body.filename)
    with tenant_session(p.tenant_id) as db:
        repo.create_document(
            db,
            p.tenant_id,
            document_id=doc_id,
            title=body.title or body.filename,
            filename=body.filename,
            mime=mime,
            object_key=key,
            status="pending_upload",
            size_bytes=body.size_bytes,
        )
    expires = 900
    return schemas.CreateDocumentResponse(
        document_id=doc_id,
        upload_url=storage.presign_put(key, mime, expires),
        upload_headers={"Content-Type": mime},
        expires_in=expires,
    )


@app.post(
    "/v1/documents/{document_id}/complete",
    response_model=schemas.TaskAccepted,
    status_code=202,
    tags=["documents"],
)
def complete_upload(document_id: uuid.UUID, p: CurrentPrincipal) -> schemas.TaskAccepted:
    with tenant_session(p.tenant_id) as db:
        doc = repo.get_document(db, p.tenant_id, str(document_id))
    if doc is None:
        raise HTTPException(404, "document not found")
    size = storage.head(doc.object_key)
    if size is None:
        raise HTTPException(409, "the file has not been uploaded yet")
    if size > settings.max_upload_bytes:
        raise HTTPException(413, "uploaded file is too large")
    with tenant_session(p.tenant_id) as db:
        if doc.status == "pending_upload":
            repo.set_document_status(db, p.tenant_id, doc.id, "uploaded", size_bytes=size)
    return schemas.TaskAccepted(task_id=_enqueue_ingest(p.tenant_id, doc.id, p.user_id))


@app.post("/v1/documents/upload", response_model=schemas.UploadAccepted, status_code=202, tags=["documents"])
async def upload_document(
    p: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
) -> schemas.UploadAccepted:
    """Upload through the API (CLI, tests, small files). The web app uses presigned uploads instead."""
    data = await file.read(settings.max_upload_bytes + 1)
    mime = _check_upload(file.filename or "document", file.content_type, len(data))
    doc_id = str(uuid.uuid4())
    key = storage.object_key(p.tenant_id, doc_id, file.filename or "document")
    storage.put_bytes(key, data, mime)
    with tenant_session(p.tenant_id) as db:
        repo.create_document(
            db,
            p.tenant_id,
            document_id=doc_id,
            title=title or file.filename or "Untitled",
            filename=file.filename or "document",
            mime=mime,
            object_key=key,
            status="uploaded",
            size_bytes=len(data),
        )
    return schemas.UploadAccepted(task_id=_enqueue_ingest(p.tenant_id, doc_id, p.user_id), document_id=doc_id)


@app.get("/v1/documents", response_model=schemas.DocumentPage, tags=["documents"])
def list_documents(
    p: CurrentPrincipal,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.DocumentPage:
    with tenant_session(p.tenant_id) as db:
        rows = repo.list_documents(db, p.tenant_id, query=q, limit=limit, offset=offset)
        total = repo.count_documents(db, p.tenant_id)
    return schemas.DocumentPage(items=[_doc_out(r) for r in rows], total=total, limit=limit, offset=offset)


@app.get("/v1/documents/{document_id}", response_model=schemas.Document, tags=["documents"])
def get_document(document_id: uuid.UUID, p: CurrentPrincipal) -> schemas.Document:
    with tenant_session(p.tenant_id) as db:
        doc = repo.get_document(db, p.tenant_id, str(document_id))
    if doc is None:
        raise HTTPException(404, "document not found")
    return _doc_out(doc)


@app.get(
    "/v1/documents/{document_id}/file",
    tags=["documents"],
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def document_file(document_id: uuid.UUID, p: CurrentPrincipal) -> Response:
    """The original file, for the source panel (PDF.js). Served through the API so the tenant check applies."""
    with tenant_session(p.tenant_id) as db:
        doc = repo.get_document(db, p.tenant_id, str(document_id))
    if doc is None or doc.status == "pending_upload":
        raise HTTPException(404, "document not found")
    return Response(
        storage.get_bytes(doc.object_key),
        media_type=doc.mime,
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@app.delete(
    "/v1/documents/{document_id}", response_model=schemas.TaskAccepted, status_code=202, tags=["documents"]
)
def delete_document(document_id: uuid.UUID, p: AdminPrincipal) -> schemas.TaskAccepted:
    from cortex.worker.tasks import delete_document_task

    with tenant_session(p.tenant_id) as db:
        doc = repo.get_document(db, p.tenant_id, str(document_id))
        if doc is None:
            raise HTTPException(404, "document not found")
        task_id, created = repo.create_task(
            db,
            p.tenant_id,
            "delete",
            {"document_id": doc.id},
            idempotency_key=f"delete:{doc.id}",
            created_by=p.user_id,
        )
    if created:
        delete_document_task.delay(p.tenant_id, task_id, doc.id, doc.object_key, p.user_id)
    return schemas.TaskAccepted(task_id=task_id, created=created)


# ------------------------------------------------------------------------------------------------------- ask
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")


@app.post("/v1/ask", response_model=schemas.TaskAccepted, status_code=202, tags=["ask"])
def ask(
    body: schemas.AskRequest,
    p: CurrentPrincipal,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> schemas.TaskAccepted:
    from cortex.worker.tasks import ask_task

    if idempotency_key is not None and not _IDEMPOTENCY.match(idempotency_key):
        raise HTTPException(400, "Idempotency-Key must be 8-128 characters of [A-Za-z0-9_.:-]")
    with tenant_session(p.tenant_id) as db:
        task_id, created = repo.create_task(
            db,
            p.tenant_id,
            "ask",
            {"question": body.question.strip(), "router": body.router},
            idempotency_key=idempotency_key,
            created_by=p.user_id,
        )
    if created:
        ask_task.delay(p.tenant_id, task_id)
    return schemas.TaskAccepted(task_id=task_id, created=created)


def _answer_out(a: dict[str, Any]) -> schemas.Answer:
    return schemas.Answer(**a)


@app.get("/v1/tasks/{task_id}", response_model=schemas.Task, tags=["tasks"])
def get_task(task_id: uuid.UUID, p: CurrentPrincipal) -> schemas.Task:
    with tenant_session(p.tenant_id) as db:
        t = repo.get_task(db, p.tenant_id, str(task_id))
        ans = repo.get_answer(db, p.tenant_id, str(task_id)) if t and t.kind == "ask" else None
    if t is None:
        raise HTTPException(404, "task not found")
    return schemas.Task(
        id=t.id,
        kind=t.kind,
        status=t.status,
        input=t.input,
        result=t.result,
        error=t.error,
        attempts=t.attempts,
        created_at=t.created_at,
        started_at=t.started_at,
        finished_at=t.finished_at,
        answer=_answer_out(ans) if ans else None,
    )


@app.get(
    "/v1/tasks/{task_id}/events",
    tags=["tasks"],
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-sent events"}},
)
async def task_events(
    task_id: uuid.UUID,
    p: CurrentPrincipal,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """SSE: ``status``, ``step``, ``evidence``, ``token``, ``code``, ``answer``, then ``done`` / ``error`` /
    ``cancelled``. Event ids are Redis Stream ids; reconnect with ``Last-Event-ID`` to resume without gaps."""
    with tenant_session(p.tenant_id) as db:
        t = repo.get_task(db, p.tenant_id, str(task_id))
    if t is None:
        raise HTTPException(404, "task not found")

    async def gen() -> AsyncIterator[bytes]:
        yield b"retry: 2000\n\n"
        async for item in read_events(str(task_id), last_event_id):
            if item is None:
                yield b": keep-alive\n\n"
                continue
            entry_id, event, data = item
            yield f"id: {entry_id}\nevent: {event}\ndata: {json.dumps(data)}\n\n".encode()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/v1/tasks/{task_id}/cancel", response_model=schemas.TaskAccepted, status_code=202, tags=["tasks"])
def cancel_task(task_id: uuid.UUID, p: CurrentPrincipal) -> schemas.TaskAccepted:
    from cortex.streaming import EventSink
    from cortex.worker.tasks import cancel_key

    tid = str(task_id)
    with tenant_session(p.tenant_id) as db:
        t = repo.get_task(db, p.tenant_id, tid)
        if t is None:
            raise HTTPException(404, "task not found")
        if t.status in ("succeeded", "failed", "cancelled"):
            return schemas.TaskAccepted(task_id=tid, status=t.status, created=False)
        redis.Redis.from_url(settings.redis_url).set(cancel_key(tid), "1", ex=3600)
        if t.status == "queued":
            repo.finish_task(db, p.tenant_id, tid, "cancelled", error="cancelled by user")
            EventSink(tid).emit("cancelled", {"task_id": tid})
    return schemas.TaskAccepted(task_id=tid, status="cancelled", created=False)


@app.post("/v1/answers/{task_id}/feedback", status_code=204, tags=["ask"])
def feedback(task_id: uuid.UUID, body: schemas.FeedbackRequest, p: CurrentPrincipal) -> Response:
    with tenant_session(p.tenant_id) as db:
        if repo.get_answer(db, p.tenant_id, str(task_id)) is None:
            raise HTTPException(404, "answer not found")
        repo.upsert_feedback(db, p.tenant_id, str(task_id), p.user_id, body.rating, body.comment)
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------- chunks/graph
_PAGE = re.compile(r"(?:^|> )Page (\d+)$")


@app.get("/v1/chunks/{chunk_id}", response_model=schemas.ChunkOut, tags=["sources"])
def get_chunk(chunk_id: uuid.UUID, p: CurrentPrincipal) -> schemas.ChunkOut:
    with tenant_session(p.tenant_id) as db:
        rows = repo.get_chunks(db, p.tenant_id, [str(chunk_id)])
    if not rows:
        raise HTTPException(404, "passage not found")
    c = rows[0]
    m = _PAGE.search(c.heading_path)
    return schemas.ChunkOut(
        id=c.id,
        document_id=c.document_id,
        document_title=c.document_title,
        position=c.position,
        heading_path=c.heading_path,
        text=c.text,
        char_start=c.char_start,
        char_end=c.char_end,
        filename=c.filename,
        mime=c.mime,
        page=int(m.group(1)) if m else None,
    )


@app.get("/v1/graph/stats", response_model=schemas.GraphStats, tags=["sources"])
def graph_stats(p: CurrentPrincipal) -> schemas.GraphStats:
    from cortex.graph.store import GraphStore

    try:
        st = GraphStore().stats(p.tenant_id)
    except Exception as exc:
        raise HTTPException(503, "knowledge graph unavailable") from exc
    return schemas.GraphStats(**{k: st.get(k, 0) for k in ("entities", "relations", "chunks")})


# ------------------------------------------------------------------------------------------------------ admin
@app.get("/v1/admin/usage", response_model=schemas.Usage, tags=["admin"])
def usage(p: AdminPrincipal, days: Annotated[int, Query(ge=1, le=365)] = 30) -> schemas.Usage:
    with tenant_session(p.tenant_id) as db:
        return schemas.Usage(**repo.usage_summary(db, p.tenant_id, days))


@app.get("/v1/admin/eval-runs", response_model=list[schemas.EvalRun], tags=["admin"])
def eval_runs(p: AdminPrincipal, limit: Annotated[int, Query(ge=1, le=500)] = 200) -> list[schemas.EvalRun]:
    with get_engine().connect() as c:
        rows = (
            c.execute(
                text(
                    "SELECT id, created_at, name, git_commit, config, metrics FROM eval_runs ORDER BY created_at DESC"
                    " LIMIT :l"
                ),
                {"l": limit},
            )
            .mappings()
            .all()
        )
    return [schemas.EvalRun(**dict(r)) for r in rows]


_VITALS = {"LCP", "INP", "CLS", "FCP", "TTFB", "ERROR"}


@app.post("/v1/rum", status_code=204, include_in_schema=False)
async def rum(request: Request) -> Response:
    """Real-user monitoring beacon (free replacement for CloudWatch RUM). Unauthenticated, tiny, metrics only."""
    body = await request.body()
    if len(body) > 2048:
        return Response(status_code=413)
    try:
        m = json.loads(body)
        name, value, rating = str(m["name"]), float(m.get("value", 0)), str(m.get("rating", "unknown"))[:20]
    except (ValueError, KeyError, TypeError):
        return Response(status_code=400)
    if name not in _VITALS or rating not in {"good", "needs-improvement", "poor", "unknown"}:
        return Response(status_code=400)
    if name == "ERROR":
        metrics.WEB_ERRORS.inc()
    else:
        metrics.WEB_VITALS.labels(name=name, rating=rating).observe(value)
    return Response(status_code=204)


@app.get("/v1/meta", tags=["meta"])
def meta() -> dict[str, Any]:
    """Public, non-sensitive configuration the UI shows (model names, limits)."""
    return {
        "max_upload_bytes": settings.max_upload_bytes,
        "supported_types": sorted(SUPPORTED_MIME),
        "models": {
            "small": settings.model_small,
            "large": settings.model_large,
            "provider": settings.model_provider,
        },
        "embedding_model": settings.embedding_model,
        "budgets": {"steps": settings.agent_max_steps, "tokens": settings.agent_max_tokens},
    }
