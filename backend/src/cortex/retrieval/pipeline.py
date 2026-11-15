"""Retrieval configurations used by the agents and the evaluation harness.

``dense`` · ``sparse`` · ``fused`` (RRF of both) · ``reranked`` (cross-encoder over the fused top 20, keep 5).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from cortex.config import get_settings
from cortex.ingest.chunk import embed_text
from cortex.observability import metrics
from cortex.retrieval.base import Candidate, Retriever
from cortex.retrieval.fusion import rrf

Mode = Literal["dense", "sparse", "fused", "reranked"]
ScoreFn = Callable[[str, Sequence[str]], list[float]]


@dataclass
class HybridRetriever:
    dense: Retriever
    sparse: Retriever
    rerank_scores: ScoreFn | None = None
    mode: Mode = "reranked"
    rrf_k: int = 60
    candidates: int = 20

    @property
    def name(self) -> str:
        return self.mode

    def search(self, tenant_id: str, query: str, k: int) -> list[Candidate]:
        if self.mode == "dense":
            return self.dense.search(tenant_id, query, k)
        if self.mode == "sparse":
            return self.sparse.search(tenant_id, query, k)
        pool = max(k, self.candidates)
        fused = rrf(
            [self.dense.search(tenant_id, query, pool), self.sparse.search(tenant_id, query, pool)],
            k=self.rrf_k,
            limit=pool,
        )
        if self.mode == "fused" or self.rerank_scores is None:
            return fused[:k]
        return rerank(query, fused[: self.candidates], self.rerank_scores, k)


def rerank(query: str, cands: Sequence[Candidate], score: ScoreFn, k: int) -> list[Candidate]:
    with metrics.RETRIEVAL_LATENCY.labels(stage="rerank").time():
        scores = score(query, [embed_text(c.heading_path, c.text) for c in cands])
    out = []
    for c, s in zip(cands, scores, strict=True):
        out.append(
            Candidate(
                chunk_id=c.chunk_id,
                score=s,
                source="rerank",
                text=c.text,
                heading_path=c.heading_path,
                document_id=c.document_id,
                ranks={**c.ranks},
            )
        )
    out.sort(key=lambda c: (-c.score, c.chunk_id))
    for i, c in enumerate(out, start=1):
        c.ranks["rerank"] = i
    return out[:k]


def build_retriever(mode: Mode | None = None) -> HybridRetriever:
    """Production wiring with the pinned embedding model and reranker."""
    from cortex.ingest.embed import get_embedder, get_reranker
    from cortex.retrieval.dense import DenseRetriever
    from cortex.retrieval.sparse import SparseRetriever

    s = get_settings()
    mode = mode or "reranked"
    return HybridRetriever(
        dense=DenseRetriever(get_embedder().embed_query),
        sparse=SparseRetriever(),
        rerank_scores=get_reranker().scores if mode == "reranked" else None,
        mode=mode,
        rrf_k=s.rrf_k,
        candidates=s.rerank_candidates,
    )
