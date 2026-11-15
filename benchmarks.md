# Benchmarks

Every row links to the report or test that produced it. Hardware: laptop, 20 logical CPUs, 16 GB RAM (Docker/WSL
12 GB), NVIDIA RTX 4060 Ti 8 GB. Corpus: 347 Kubernetes concept and glossary pages (CC BY 4.0, commit `109ff5a`).
Intervals are 95 % bootstrap intervals over questions (1,000 resamples); comparisons are paired.

## Ingestion

| Measure | Value | Source |
|---|---|---|
| Documents → chunks | 347 → 2,995 (≤ 400 model tokens each) | `cortex ingest-dir`, 2026-11-15 |
| Embedding throughput (CPU, bge-small-en-v1.5) | 347 docs in 142 s ≈ 21 chunks/s | same run |
| Graph extraction (qwen3.5:2b, GPU, 2 parallel) | ≈ 2.7 s per chunk; 0 % invalid JSON on the first 160 chunks | `cortex extract` log |

## Retrieval ablation — 2026-11-15 (`eval/reports/2026-11-15T120750Z-retrieval.md`)

57 answerable questions (39 content, 18 relationship), k = 10.

| Config | Recall@1 | Recall@5 | Recall@10 | MRR | p50 latency |
|---|---|---|---|---|---|
| dense (pgvector HNSW) | 36.8 [24.6, 49.1] | 83.3 [72.8, 91.2] | **93.0** [86.0, 98.2] | 0.583 | 19 ms |
| sparse (Postgres FTS) | 17.5 [8.8, 28.1] | 43.9 [31.6, 56.1] | 48.2 [36.0, 61.4] | 0.279 | 12 ms |
| fused (RRF, k = 60) | 33.3 [21.1, 47.4] | 64.0 [51.8, 76.3] | 86.8 [78.1, 94.7] | 0.482 | 30 ms |
| fused + cross-encoder | **52.6** [40.4, 66.7] | **92.1** [84.2, 98.2] | **95.6** [89.5, 100] | **0.693** | 557 ms |

Paired against dense (Recall@10): sparse −44.7 pts (significant); fused −6.1 pts, p = 0.22 (noise);
reranked +2.6 pts, p = 0.50 (noise). By type, Recall@10: content 100 % for dense and reranked; relationship
77.8 % → 86.1 %.

**Reading.** The reranker is the win at the top of the list (Recall@1 +15.8 pts, MRR +0.11); at Recall@10 nothing
beats dense outside the noise with 57 questions. Postgres full-text search is weak on this corpus.

## Correctness tests

| Area | Result | Source |
|---|---|---|
| Unit tests (chunking, RRF, guards, agents, prompt-injection filters, auth) | 56 passed | `backend/tests/unit` |
| Integration (RLS, filtered HNSW, idempotency, streaming, Neo4j isolation, API flow) | 28 passed | `backend/tests/integration` |
| Sandbox escape tests | 11 passed, every escape fails safely | `backend/tests/sandbox` |
| Front-end unit tests | 11 passed | `web/src/**/*.test.ts(x)` |
| End-to-end journeys, desktop + phone, axe WCAG 2.2 AA | 11 passed, 0 violations | `web/e2e` |
| Filtered HNSW, 1 % tenant | without iterative scan < 10 of 10 rows; with it 10/10, recall vs exact ≥ 0.9 | `test_filtered_hnsw.py` |
