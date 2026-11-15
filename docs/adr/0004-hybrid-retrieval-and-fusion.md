# ADR 0004 — Hybrid retrieval: Postgres FTS + pgvector, Reciprocal Rank Fusion (k = 60), then rerank

Status: accepted, with a measured caveat · 2026-11-15

## Decision
- Sparse: PostgreSQL full-text search (`ts_rank_cd`, headings weighted A), tenant-filtered in the same query, the
  question rewritten as an OR of its stemmed terms. Not true BM25 — ParadeDB `pg_search` is, but it is not
  available on Amazon RDS; staying portable wins.
- Dense: pgvector HNSW with `hnsw.iterative_scan = relaxed_order` (a 1 % tenant still gets k results) and a strict
  re-sort (`ORDER BY distance + 0` — Postgres 17+ otherwise skips the outer sort; found by a test).
- Fusion: RRF, score = Σ 1/(k + rank) with **k = 60** (Cormack, Clarke & Büttcher 2009): rank-based, so cosine
  similarities and FTS ranks — on unrelated scales — merge without tuned weights.
- The cross-encoder reranks the fused top 20.

## Evidence (first measured ablation, 2026-11-15)
| Config | Recall@10 | Recall@1 | MRR |
|---|---|---|---|
| dense | 93.0 [86.0, 98.2] | 36.8 | 0.583 |
| sparse | 48.2 [36.0, 61.4] | 17.5 | 0.279 |
| fused (RRF) | 86.8 [78.1, 94.7] | 33.3 | 0.482 |
| fused + rerank | 95.6 [89.5, 100] | 52.6 | 0.693 |

Honest reading: on this corpus Postgres FTS is weak, and fusing it **does not help** Recall@10 (−6.1 pts vs dense,
p = 0.22 — within noise). The reranker is what moves the top of the ranking. Hybrid stays because keyword search
rescues exact identifiers (flags, field names) that embeddings blur, and the reranker absorbs the noise sparse adds.
Next experiments: true BM25 locally, and RRF with a dense-weighted k.
