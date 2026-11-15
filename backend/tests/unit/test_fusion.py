from __future__ import annotations

import pytest

from cortex.retrieval.base import Candidate
from cortex.retrieval.fusion import rrf


def ranking(source: str, ids: list[str]) -> list[Candidate]:
    return [Candidate(chunk_id=i, score=100.0 - n, source=source) for n, i in enumerate(ids)]


def test_rrf_uses_ranks_with_k_60() -> None:
    fused = rrf([ranking("dense", ["a", "b", "c"]), ranking("sparse", ["c", "a"])], k=60)
    scores = {c.chunk_id: c.score for c in fused}
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["c"] == pytest.approx(1 / 63 + 1 / 61)
    assert scores["b"] == pytest.approx(1 / 62)
    assert [c.chunk_id for c in fused] == ["a", "c", "b"]
    assert fused[0].ranks == {"dense": 1, "sparse": 2}


def test_raw_scores_do_not_matter() -> None:
    a = ranking("dense", ["x", "y"])
    a[0].score, a[1].score = 0.0001, 0.00001  # tiny cosine scores
    b = ranking("sparse", ["y", "x"])
    b[0].score, b[1].score = 9999.0, 1.0  # huge FTS scores
    fused = rrf([a, b])
    assert fused[0].score == pytest.approx(fused[1].score)


def test_duplicates_within_one_ranking_count_once() -> None:
    fused = rrf([ranking("dense", ["a", "a", "b"])])
    assert {c.chunk_id: c.score for c in fused}["a"] == pytest.approx(1 / 61)


def test_limit_and_invalid_k() -> None:
    assert len(rrf([ranking("dense", list("abcdef"))], limit=3)) == 3
    with pytest.raises(ValueError, match="positive"):
        rrf([], k=0)
