"""Operator CLI: ``python -m cortex.cli <command>`` (or the ``cortex`` entry point)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from cortex.config import get_settings


def cmd_migrate(_: argparse.Namespace) -> None:
    from alembic import command
    from alembic.config import Config

    candidates = [Path.cwd() / "alembic.ini", Path(__file__).resolve().parents[2] / "alembic.ini"]
    ini = next((p for p in candidates if p.exists()), None)
    if ini is None:
        raise SystemExit("alembic.ini not found (run from the backend directory)")
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", get_settings().migration_database_url)
    command.upgrade(cfg, "head")
    print("migrations applied")


def cmd_init(_: argparse.Namespace) -> None:
    from cortex import storage
    from cortex.graph.store import GraphStore

    storage.ensure_bucket()
    GraphStore().ensure_schema()
    print("bucket and graph schema ready")


def cmd_tenant(args: argparse.Namespace) -> None:
    from cortex.db.repo import ensure_tenant

    ensure_tenant(args.tenant, args.name, args.confidential)
    print(f"tenant {args.tenant} ready (confidential={args.confidential})")


def cmd_ingest_dir(args: argparse.Namespace) -> None:
    """Load a folder synchronously in this process (bulk corpus loading); idempotent per file path."""
    from cortex import storage
    from cortex.db import repo
    from cortex.db.session import tenant_session
    from cortex.ingest.embed import get_embedder
    from cortex.ingest.parse import EXTENSIONS, ParseError, mime_for
    from cortex.ingest.service import ingest_document

    root = Path(args.path)
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS)
    if args.limit:
        files = files[: args.limit]
    emb = get_embedder()
    repo.ensure_tenant(args.tenant)
    started, total_chunks = time.perf_counter(), 0
    for i, f in enumerate(files, start=1):
        rel = f.relative_to(root).as_posix()
        doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"cortex:{args.tenant}:{rel}"))
        try:
            mime = mime_for(f.name)
        except ParseError:
            continue
        key = storage.object_key(args.tenant, doc_id, f.name)
        data = f.read_bytes()
        storage.put_bytes(key, data, mime)
        with tenant_session(args.tenant) as db:
            if repo.get_document(db, args.tenant, doc_id) is None:
                repo.create_document(
                    db,
                    args.tenant,
                    document_id=doc_id,
                    title=f.stem,
                    filename=rel,
                    mime=mime,
                    object_key=key,
                    status="uploaded",
                    size_bytes=len(data),
                )
        res = ingest_document(args.tenant, doc_id, embedder=emb)
        total_chunks += len(res.chunk_ids)
        if i % 25 == 0 or i == len(files):
            print(
                f"  {i}/{len(files)} files, {total_chunks} chunks, {time.perf_counter() - started:.0f}s",
                flush=True,
            )
    print(f"ingested {len(files)} files → {total_chunks} chunks in {time.perf_counter() - started:.1f}s")


def cmd_extract(args: argparse.Namespace) -> None:
    """Build the knowledge graph for a tenant's documents in this process."""
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import text

    from cortex.db.session import tenant_session
    from cortex.graph.extract import ExtractionStats, extract_into_graph
    from cortex.graph.store import GraphStore
    from cortex.models.llm import CallContext, get_llm

    store = GraphStore()
    store.ensure_schema()
    with tenant_session(args.tenant) as db:
        docs = [
            r[0]
            for r in db.execute(
                text(
                    "SELECT id::text FROM documents WHERE tenant_id = :t AND status = 'ready' ORDER BY title"
                ),
                {"t": args.tenant},
            )
        ]
    if args.limit:
        docs = docs[: args.limit]
    total = ExtractionStats()
    started = time.perf_counter()
    ctx = CallContext(tenant_id=args.tenant, log_calls=not args.no_log)

    def one(doc_id: str) -> ExtractionStats:
        if args.resume:
            with tenant_session(args.tenant) as db:
                current = {
                    r[0]
                    for r in db.execute(
                        text(
                            "SELECT id::text FROM chunks WHERE tenant_id = :t AND document_id = CAST(:d AS uuid)"
                        ),
                        {"t": args.tenant, "d": doc_id},
                    )
                }
            if current and current == store.chunk_ids_for_document(args.tenant, doc_id):
                return ExtractionStats()  # already extracted (resume after an interruption)
        with tenant_session(args.tenant) as db:
            chunks = [
                (r[0], r[1], r[2])
                for r in db.execute(
                    text(
                        "SELECT id::text, heading_path, text FROM chunks WHERE tenant_id = :t AND document_id ="
                        " CAST(:d AS uuid) ORDER BY position"
                    ),
                    {"t": args.tenant, "d": doc_id},
                )
            ]
        return extract_into_graph(get_llm(), ctx, store, doc_id, chunks)

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for i, st in enumerate(pool.map(one, docs), start=1):
            total.chunks += st.chunks
            total.failed += st.failed
            total.entities += st.entities
            total.relations += st.relations
            if i % 10 == 0 or i == len(docs):
                print(
                    f"  {i}/{len(docs)} docs, {total.chunks} chunks, failure rate {total.failure_rate:.1%},"
                    f" {time.perf_counter() - started:.0f}s",
                    flush=True,
                )
    summary = {
        "documents": len(docs),
        "chunks": total.chunks,
        "failed": total.failed,
        "failure_rate": round(total.failure_rate, 4),
        "entities_written": total.entities,
        "relations_written": total.relations,
        "tokens": ctx.usage.total_tokens,
        "seconds": round(time.perf_counter() - started, 1),
        "graph": store.stats(args.tenant),
    }
    print(json.dumps(summary, indent=2))


def cmd_ask(args: argparse.Namespace) -> None:
    from cortex.answering import answer_question

    def on_token(t: str) -> None:
        sys.stdout.write(t)
        sys.stdout.flush()

    res = answer_question(
        args.tenant,
        args.question,
        on_token=on_token if args.stream else None,
        router=args.router,
        log_calls=False,
    )
    print("\n" if args.stream else "", res["answer"] if not args.stream else "", sep="")
    print("\n--- evidence")
    for e in res["evidence"]:
        print(f"[{e['n']}] {e['title']} — {e['heading']} ({e['source']})")
    keys = (
        "route",
        "partial",
        "not_found",
        "stop_reason",
        "steps",
        "input_tokens",
        "output_tokens",
        "latency_ms",
    )
    print("---", json.dumps({k: res[k] for k in keys}))


def cmd_token(args: argparse.Namespace) -> None:
    """Get an access token from Keycloak with the password grant (development realm only)."""
    import httpx

    s = get_settings()
    resp = httpx.post(
        f"{s.oidc_issuer}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": args.client,
            "username": args.username,
            "password": args.password,
            "scope": "openid",
        },
        timeout=10,
    )
    resp.raise_for_status()
    print(resp.json()["access_token"])


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="cortex")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    t = sub.add_parser("tenant")
    t.add_argument("tenant")
    t.add_argument("--name")
    t.add_argument("--confidential", action="store_true")
    t.set_defaults(fn=cmd_tenant)
    i = sub.add_parser("ingest-dir")
    i.add_argument("tenant")
    i.add_argument("path")
    i.add_argument("--limit", type=int)
    i.set_defaults(fn=cmd_ingest_dir)
    e = sub.add_parser("extract")
    e.add_argument("tenant")
    e.add_argument("--limit", type=int)
    e.add_argument("--parallel", type=int, default=2)
    e.add_argument("--no-log", action="store_true")
    e.add_argument(
        "--resume", action="store_true", help="skip documents whose chunks are all in the graph already"
    )
    e.set_defaults(fn=cmd_extract)
    a = sub.add_parser("ask")
    a.add_argument("tenant")
    a.add_argument("question")
    a.add_argument("--router", choices=["llm", "rules"], default="llm")
    a.add_argument("--stream", action="store_true")
    a.set_defaults(fn=cmd_ask)
    k = sub.add_parser("token")
    k.add_argument("username")
    k.add_argument("password")
    k.add_argument("--client", default="cortex-cli")
    k.set_defaults(fn=cmd_token)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
