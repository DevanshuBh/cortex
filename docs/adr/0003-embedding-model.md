# ADR 0003 — Embedding model: BAAI/bge-small-en-v1.5 (pinned), cross-encoder reranker

Status: accepted · 2026-11-14

## Decision
- Embeddings: `BAAI/bge-small-en-v1.5`, revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, 384 dimensions,
  512-token input, MIT licence; queries use the model's retrieval instruction prefix; vectors are normalised and
  searched with cosine distance (HNSW, m = 16, ef_construction = 64, ef_search = 100).
- Reranker: `cross-encoder/ms-marco-MiniLM-L6-v2`, revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`, over the
  fused top 20, keep 5.
- Both are baked into the backend image at build time, so containers start offline.

## Alternatives
all-MiniLM-L6-v2 (same size, but a 256-token limit forces tiny chunks); larger embedders (better quality, 3–10×
slower on CPU and bigger vectors — 4.6 GB at 3 M chunks already, see design §4).

## Consequences
Changing the model is a re-embedding migration: build a shadow index, evaluate both, switch reads, drop the old one
(staff step S.6). Vectors from two models never share an index.

## Evidence (eval/reports, 57 answerable questions, 95 % bootstrap CIs)
Dense Recall@10 93.0 % [86.0, 98.2]; with the reranker 95.6 % [89.5, 100] and Recall@1 52.6 % vs 36.8 %.
