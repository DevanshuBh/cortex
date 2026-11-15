"""Reciprocal Rank Fusion (Cormack, Clarke & Büttcher, 2009): score(d) = Σ_r 1 / (k + rank_r(d)), k = 60.

Rank-based, so dense cosine similarities and full-text ranks — which live on unrelated scales — can be merged
without tuning weights (docs/adr/0004).
"""

from __future__ import annotations

from collections.abc import Sequence

from cortex.retrieval.base import Candidate

DEFAULT_K = 60


def rrf(
    rankings: Sequence[Sequence[Candidate]], *, k: int = DEFAULT_K, limit: int | None = None
) -> list[Candidate]:
    if k <= 0:
        raise ValueError("RRF constant k must be positive")
    fused: dict[str, Candidate] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, cand in enumerate(ranking, start=1):
            if cand.chunk_id in seen:  # a ranking contributes each document once, at its best rank
                continue
            seen.add(cand.chunk_id)
            entry = fused.get(cand.chunk_id)
            if entry is None:
                entry = Candidate(
                    chunk_id=cand.chunk_id,
                    score=0.0,
                    source="rrf",
                    text=cand.text,
                    heading_path=cand.heading_path,
                    document_id=cand.document_id,
                )
                fused[cand.chunk_id] = entry
            entry.score += 1.0 / (k + rank)
            entry.ranks[cand.source] = rank
            if not entry.text and cand.text:
                entry.text, entry.heading_path, entry.document_id = (
                    cand.text,
                    cand.heading_path,
                    cand.document_id,
                )
    out = sorted(fused.values(), key=lambda c: (-c.score, min(c.ranks.values()), c.chunk_id))
    return out[:limit] if limit is not None else out
