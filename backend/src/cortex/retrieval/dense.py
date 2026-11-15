"""Dense retrieval with pgvector HNSW, tenant-filtered in the same query.

pgvector applies the tenant WHERE clause *after* the HNSW scan, so a small tenant can get far fewer than k rows.
``hnsw.iterative_scan = relaxed_order`` keeps scanning until k filtered rows are found; relaxed order means the
rows must be re-sorted by distance, which the outer query does (design §8.2, test_filtered_hnsw.py).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from sqlalchemy import text

from cortex.config import get_settings
from cortex.db.repo import vec_literal
from cortex.db.session import set_search_options, tenant_session
from cortex.observability import metrics
from cortex.retrieval.base import Candidate

QueryEmbedder = Callable[[str], np.ndarray]

DENSE_SQL = text(
    """
    WITH nearest AS MATERIALIZED (
        SELECT id, document_id, heading_path, text, embedding <=> CAST(:q AS vector) AS distance
        FROM chunks
        WHERE tenant_id = :t AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:q AS vector)
        LIMIT :k
    )
    -- "+ 0": on Postgres 17+ the planner propagates the CTE's ORDER BY and would skip this sort, but with
    -- relaxed_order the CTE rows are NOT strictly ordered (caught by test_filtered_hnsw.py).
    SELECT id::text, document_id::text, heading_path, text, distance FROM nearest ORDER BY distance + 0 LIMIT :k
    """
)


class DenseRetriever:
    name = "dense"

    def __init__(self, embed_query: QueryEmbedder, ef_search: int | None = None) -> None:
        self._embed = embed_query
        self._ef = ef_search or get_settings().hnsw_ef_search

    def search(self, tenant_id: str, query: str, k: int) -> list[Candidate]:
        with metrics.RETRIEVAL_LATENCY.labels(stage="embed_query").time():
            q = vec_literal(self._embed(query))
        return self.search_vector(tenant_id, q, k)

    def search_vector(self, tenant_id: str, q: str, k: int) -> list[Candidate]:
        with metrics.RETRIEVAL_LATENCY.labels(stage="dense").time(), tenant_session(tenant_id) as db:
            set_search_options(db, max(self._ef, k))
            rows = db.execute(DENSE_SQL, {"q": q, "t": tenant_id, "k": k}).all()
        return [
            Candidate(
                chunk_id=r[0],
                document_id=r[1],
                heading_path=r[2],
                text=r[3],
                score=1.0 - float(r[4]),
                source="dense",
                ranks={"dense": i},
            )
            for i, r in enumerate(rows, start=1)
        ]
