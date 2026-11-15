"""Sparse retrieval with PostgreSQL full-text search, tenant-filtered in the same query.

``websearch_to_tsquery`` ANDs terms, which is too strict for natural-language questions; the query is rewritten
as an OR of its stemmed lexemes and ranked with ``ts_rank_cd`` (cover density), heading matches weighted higher.
This is not true BM25 (ParadeDB pg_search is; it is not available on RDS — docs/adr/0004).
"""

from __future__ import annotations

import re

from sqlalchemy import text

from cortex.db.session import tenant_session
from cortex.observability import metrics
from cortex.retrieval.base import Candidate

SPARSE_SQL = text(
    """
    WITH q AS (SELECT to_tsquery('english', :tsq) AS query)
    SELECT c.id::text, c.document_id::text, c.heading_path, c.text, ts_rank_cd(c.tsv, q.query, 32) AS rank
    FROM chunks c, q
    WHERE c.tenant_id = :t AND c.tsv @@ q.query
    ORDER BY rank DESC, c.id
    LIMIT :k
    """
)

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")


def or_query(question: str) -> str | None:
    """Turn free text into an OR tsquery of safe terms. Returns None when nothing searchable remains."""
    terms = []
    for w in _WORD.findall(question):
        w = w.strip(".-_").lower()
        if len(w) >= 2 and w.replace("-", "").replace(".", "").replace("_", "").isalnum():
            terms.append(w.replace("'", ""))
    if not terms:
        return None
    # Each term is passed through plainto_tsquery semantics by quoting; dashes/dots split into phrase parts.
    parts = []
    for t in dict.fromkeys(terms):
        pieces = [p for p in re.split(r"[-._]", t) if p]
        parts.append(" <-> ".join(pieces) if len(pieces) > 1 else pieces[0])
    return " | ".join(f"({p})" for p in parts)


class SparseRetriever:
    name = "sparse"

    def search(self, tenant_id: str, query: str, k: int) -> list[Candidate]:
        tsq = or_query(query)
        if tsq is None:
            return []
        with metrics.RETRIEVAL_LATENCY.labels(stage="sparse").time(), tenant_session(tenant_id) as db:
            rows = db.execute(SPARSE_SQL, {"tsq": tsq, "t": tenant_id, "k": k}).all()
        return [
            Candidate(
                chunk_id=r[0],
                document_id=r[1],
                heading_path=r[2],
                text=r[3],
                score=float(r[4]),
                source="sparse",
                ranks={"sparse": i},
            )
            for i, r in enumerate(rows, start=1)
        ]
