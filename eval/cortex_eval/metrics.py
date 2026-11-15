"""Retrieval metrics and the statistics behind every claim (guide steps 2.2, 2.7 and staff step S.1).

- Evidence recall@k: the share of a question's evidence items found in the top k (a multi-hop question with two
  evidence passages that finds one scores 0.5).
- MRR: reciprocal rank of the first chunk that satisfies any evidence item.
- nDCG@k with binary gains; the ideal ranking places one satisfying chunk per evidence item first.
- Bootstrap confidence intervals (resampling questions), paired bootstrap and paired permutation tests,
  and Cohen's kappa with a bootstrap interval.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from cortex_eval.labels import EvidenceLabel, RetrievedChunk, satisfied


@dataclass(frozen=True, slots=True)
class RetrievalScore:
    recall: dict[int, float]  # k -> evidence recall@k
    mrr: float
    ndcg10: float
    first_hit_rank: int | None


def score_ranking(evidence: Sequence[EvidenceLabel], ranked: Sequence[RetrievedChunk],
                  ks: Sequence[int] = (1, 3, 5, 10)) -> RetrievalScore:
    hits_per_rank = [satisfied(evidence, c) for c in ranked]
    n = len(evidence)
    recall: dict[int, float] = {}
    for k in ks:
        covered: set[int] = set()
        for h in hits_per_rank[:k]:
            covered |= h
        recall[k] = len(covered) / n if n else 0.0
    first = next((i + 1 for i, h in enumerate(hits_per_rank) if h), None)
    # nDCG@10: a rank gains 1 if it satisfies an evidence item not already covered
    dcg, covered = 0.0, set()
    for i, h in enumerate(hits_per_rank[:10]):
        new = h - covered
        if new:
            dcg += 1.0 / math.log2(i + 2)
            covered |= new
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(n, 10)))
    return RetrievalScore(recall, 1.0 / first if first else 0.0, dcg / ideal if ideal else 0.0, first)


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def percentile(xs: Sequence[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    idx = (len(s) - 1) * p
    lo, hi = math.floor(idx), math.ceil(idx)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


@dataclass(frozen=True, slots=True)
class Interval:
    value: float
    low: float
    high: float

    def fmt(self, pct: bool = True) -> str:
        if pct:
            return f"{self.value * 100:.1f} [{self.low * 100:.1f}, {self.high * 100:.1f}]"
        return f"{self.value:.3f} [{self.low:.3f}, {self.high:.3f}]"


def bootstrap_ci(values: Sequence[float], *, iterations: int = 1000, alpha: float = 0.05, seed: int = 7,
                 stat: Callable[[Sequence[float]], float] = mean) -> Interval:
    """Percentile bootstrap over questions (guide step 2.2: resample questions 1,000 times)."""
    rng = random.Random(seed)
    n = len(values)
    if n == 0:
        return Interval(float("nan"), float("nan"), float("nan"))
    samples = sorted(stat([values[rng.randrange(n)] for _ in range(n)]) for _ in range(iterations))
    return Interval(stat(values), samples[int(alpha / 2 * iterations)], samples[int((1 - alpha / 2) * iterations) - 1])


@dataclass(frozen=True, slots=True)
class PairedResult:
    mean_diff: float
    ci_low: float
    ci_high: float
    p_value: float  # two-sided, paired permutation (sign-flip) test
    effect_size: float  # Cohen's d_z of the per-question differences
    n: int

    @property
    def significant(self) -> bool:
        return self.p_value < 0.05 and not (self.ci_low <= 0.0 <= self.ci_high)

    def fmt(self) -> str:
        return (f"Δ {self.mean_diff * 100:+.1f} pts [{self.ci_low * 100:+.1f}, {self.ci_high * 100:+.1f}], "
                f"p = {self.p_value:.3f}, d_z = {self.effect_size:.2f}, n = {self.n}")


def paired_compare(a: Sequence[float], b: Sequence[float], *, iterations: int = 10_000, seed: int = 7) -> PairedResult:
    """Compare config B against config A on the same questions (B − A)."""
    if len(a) != len(b):
        raise ValueError("paired comparison needs the same questions in both configurations")
    diffs = [y - x for x, y in zip(a, b, strict=True)]
    n = len(diffs)
    rng = random.Random(seed)
    boot = sorted(mean([diffs[rng.randrange(n)] for _ in range(n)]) for _ in range(min(iterations, 2000)))
    observed = abs(mean(diffs))
    extreme = 0
    for _ in range(iterations):
        if abs(mean([d if rng.random() < 0.5 else -d for d in diffs])) >= observed - 1e-12:
            extreme += 1
    sd = math.sqrt(sum((d - mean(diffs)) ** 2 for d in diffs) / (n - 1)) if n > 1 else 0.0
    return PairedResult(
        mean_diff=mean(diffs), ci_low=boot[int(0.025 * len(boot))], ci_high=boot[int(0.975 * len(boot)) - 1],
        p_value=(extreme + 1) / (iterations + 1), effect_size=mean(diffs) / sd if sd > 0 else 0.0, n=n,
    )


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equally long, non-empty label lists")
    labels = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((a.count(lbl) / n) * (b.count(lbl) / n) for lbl in labels)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def kappa_ci(a: Sequence[str], b: Sequence[str], *, iterations: int = 1000, seed: int = 7) -> Interval:
    rng = random.Random(seed)
    n = len(a)
    vals = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        try:
            vals.append(cohen_kappa([a[i] for i in idx], [b[i] for i in idx]))
        except ZeroDivisionError:
            continue
    vals.sort()
    return Interval(cohen_kappa(a, b), vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1])


def minimum_detectable_effect(sd_of_diffs: float, n: int, z_alpha: float = 1.96, z_power: float = 0.84) -> float:
    """Smallest mean paired difference detectable at α = 0.05 with 80 % power (S.1)."""
    return (z_alpha + z_power) * sd_of_diffs / math.sqrt(n) if n else float("inf")
