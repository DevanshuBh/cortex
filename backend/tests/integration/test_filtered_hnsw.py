"""Filtered HNSW (guide step 1.4 correction): a 1 % tenant must still get k results.

pgvector applies the tenant filter after the HNSW scan. The first test reproduces the bug with iterative scans off
(forcing the HNSW plan with a filter the btree index cannot serve); the second shows ``relaxed_order`` fixes it;
the third checks the production query against exact search.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from sqlalchemy import text

from cortex.db import repo
from cortex.db.repo import vec_literal
from cortex.db.session import tenant_session
from cortex.retrieval.dense import DenseRetriever

pytestmark = pytest.mark.integration

K = 10
BIG, SMALL = 9900, 100  # the small tenant holds 1 % of all chunks
DIM = 384


def _fill(tenant: str, n: int, rng: np.random.Generator, proj: np.ndarray) -> np.ndarray:
    """Structured vectors: 16 latent dimensions projected to 384, like real embeddings (low intrinsic dimension).
    Uniform random 384-d vectors are nearly equidistant, where no ANN index (or embedding) is meaningful."""
    with tenant_session(tenant) as db:
        doc = repo.create_document(
            db, tenant, title="d", filename="d.md", mime="text/markdown", object_key="k", status="ready"
        )
    latent = rng.normal(size=(n, proj.shape[0]))
    vecs = (latent @ proj + 0.05 * rng.normal(size=(n, DIM))).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)

    rows = [
        {"t": tenant, "id": str(uuid.uuid4()), "d": doc, "pos": i, "e": vec_literal(v)}
        for i, v in enumerate(vecs)
    ]
    with tenant_session(tenant) as db:
        for start in range(0, n, 2000):
            db.execute(
                text(
                    "INSERT INTO chunks (tenant_id, id, document_id, position, text, char_start, char_end,"
                    " token_count, content_hash, chunking_version, embedding) VALUES (:t, CAST(:id AS uuid),"
                    " CAST(:d AS uuid), :pos, 'x', 0, 1, 1, 'h', 'v', CAST(:e AS vector))"
                ),
                rows[start : start + 2000],
            )
    return vecs


@pytest.fixture(scope="module")
def corpus(pg: dict[str, str]) -> tuple[str, np.ndarray]:
    rng = np.random.default_rng(7)
    big, small = f"big-{uuid.uuid4().hex[:8]}", f"small-{uuid.uuid4().hex[:8]}"
    repo.ensure_tenant(big)
    repo.ensure_tenant(small)
    proj = rng.normal(size=(16, DIM))
    _fill(big, BIG, rng, proj)
    small_vecs = _fill(small, SMALL, rng, proj)
    from cortex.db.session import get_engine

    with get_engine().begin() as c:
        c.execute(text("ANALYZE chunks"))
    return small, small_vecs


FORCED_HNSW = text(
    "SELECT id FROM chunks WHERE tenant_id = :t ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
)


def _forced(pg: dict[str, str], small: str, q: str, iterative: str) -> int:
    """Run as superuser (no RLS predicate) with btree paths disabled, so the plan must be the HNSW scan."""
    from sqlalchemy import create_engine

    engine = create_engine(pg["super"])
    with engine.begin() as c:
        for name, value in (
            ("hnsw.iterative_scan", iterative),
            ("hnsw.ef_search", "40"),
            ("enable_seqscan", "off"),
            ("enable_bitmapscan", "off"),
        ):
            c.execute(text("SELECT set_config(:n, :v, true)"), {"n": name, "v": value})
        c.execute(text("SELECT set_config('enable_indexscan', 'on', true)"))
        plan = " ".join(
            r[0] for r in c.execute(text("EXPLAIN " + FORCED_HNSW.text), {"t": small, "q": q, "k": K})
        )
        assert "chunks_embedding_hnsw" in plan, plan
        n = len(c.execute(FORCED_HNSW, {"t": small, "q": q, "k": K}).all())
    engine.dispose()
    return n


def test_post_filtering_starves_a_small_tenant(pg: dict[str, str], corpus: tuple[str, np.ndarray]) -> None:
    small, vecs = corpus
    got = [_forced(pg, small, vec_literal(vecs[i]), "off") for i in range(5)]
    assert max(got) < K, f"expected fewer than {K} rows without iterative scan, got {got}"


def test_iterative_scan_returns_k_for_a_small_tenant(
    pg: dict[str, str], corpus: tuple[str, np.ndarray]
) -> None:
    small, vecs = corpus
    assert all(_forced(pg, small, vec_literal(vecs[i]), "relaxed_order") == K for i in range(5))


def test_production_dense_query_matches_exact_search(corpus: tuple[str, np.ndarray]) -> None:
    small, vecs = corpus
    retriever = DenseRetriever(lambda _q: np.zeros(DIM), ef_search=100)
    recalls = []
    for i in range(10):
        q = vecs[i]
        got = retriever.search_vector(small, vec_literal(q), K)
        assert len(got) == K
        distances = [c.score for c in got]
        assert distances == sorted(distances, reverse=True), "results must be re-sorted after relaxed order"
        with tenant_session(small) as db:
            db.execute(text("SELECT set_config('enable_indexscan', 'off', true)"))  # exact: no ANN
            exact = {
                r[0]
                for r in db.execute(
                    text(
                        "SELECT id::text FROM chunks WHERE tenant_id = :t ORDER BY embedding <=> CAST(:q AS vector)"
                        " LIMIT :k"
                    ),
                    {"t": small, "q": vec_literal(q), "k": K},
                )
            }
        recalls.append(len(exact & {c.chunk_id for c in got}) / K)
    assert np.mean(recalls) >= 0.9
