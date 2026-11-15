"""Ingestion: object storage → parse → chunk (model tokens) → embed (only changed chunks) → Postgres.

Idempotent: re-running for the same document replaces its chunks in one transaction, so a redelivered Celery
task leaves exactly one copy. Chunk ids are deterministic (document, chunking version, position, content hash),
so unchanged chunks keep their ids — citations and graph links stay valid across re-uploads.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cortex import storage
from cortex.config import get_settings
from cortex.db import repo
from cortex.db.repo import vec_literal
from cortex.db.session import tenant_session
from cortex.ingest.chunk import chunk_document
from cortex.ingest.embed import Embedder, get_embedder
from cortex.ingest.parse import ParseError, parse
from cortex.observability import metrics
from cortex.observability.tracing import span

log = logging.getLogger(__name__)

Progress = Callable[[str, dict[str, Any]], object]


@dataclass(frozen=True, slots=True)
class IngestResult:
    document_id: str
    chunk_ids: list[str]
    reused_embeddings: int
    status: str
    error: str | None = None


def ingest_document(
    tenant_id: str,
    document_id: str,
    *,
    embedder: Embedder | None = None,
    progress: Progress | None = None,
    fetch: Callable[[str], bytes] = storage.get_bytes,
) -> IngestResult:
    s = get_settings()
    emb = embedder or get_embedder()
    notify = progress or (lambda _e, _d: None)
    with tenant_session(tenant_id) as db:
        doc = repo.get_document(db, tenant_id, document_id)
        if doc is None:
            raise LookupError(f"document {document_id} not found for tenant")
        repo.set_document_status(db, tenant_id, document_id, "parsing")
    notify("status", {"document_id": document_id, "status": "parsing"})

    with span("ingest.parse", document_id=document_id, mime=doc.mime):
        try:
            data = fetch(doc.object_key)
            parsed = parse(data, doc.mime, doc.filename)
        except ParseError as exc:
            with tenant_session(tenant_id) as db:
                repo.set_document_status(db, tenant_id, document_id, "failed", error=str(exc))
            notify("status", {"document_id": document_id, "status": "failed", "error": str(exc)})
            return IngestResult(document_id, [], 0, "failed", str(exc))

    with span("ingest.chunk", document_id=document_id):
        chunks = chunk_document(
            parsed,
            emb.count_tokens,
            max_tokens=s.chunk_max_tokens,
            overlap_tokens=s.chunk_overlap_tokens,
            model_limit=s.embedding_max_tokens,
        )
    content_hash = hashlib.sha256(data).hexdigest()
    with tenant_session(tenant_id) as db:
        repo.set_document_status(db, tenant_id, document_id, "embedding", title=parsed.title)
        existing = repo.embeddings_by_hash(db, tenant_id, document_id)
    notify("status", {"document_id": document_id, "status": "embedding", "chunks": len(chunks)})

    with span("ingest.embed", document_id=document_id, chunks=len(chunks)):
        todo = [i for i, c in enumerate(chunks) if c.content_hash not in existing]
        vectors: dict[int, str] = {}
        if todo:
            arr = emb.embed_passages([chunks[i].embed_text for i in todo])
            vectors = {i: vec_literal(v) for i, v in zip(todo, arr, strict=True)}
        embeddings = [vectors.get(i) or existing[c.content_hash] for i, c in enumerate(chunks)]

    with tenant_session(tenant_id) as db:
        ids = repo.replace_chunks(db, tenant_id, document_id, s.chunking_version, chunks, embeddings)
        repo.set_document_status(
            db,
            tenant_id,
            document_id,
            "ready",
            content_hash=content_hash,
            chunk_count=len(ids),
            chunking_version=s.chunking_version,
            size_bytes=len(data),
        )
    metrics.INGEST_CHUNKS.inc(len(ids))
    notify("status", {"document_id": document_id, "status": "ready", "chunks": len(ids)})
    log.info("ingested %s: %d chunks (%d embeddings reused)", document_id, len(ids), len(chunks) - len(todo))
    return IngestResult(document_id, ids, len(chunks) - len(todo), "ready")
