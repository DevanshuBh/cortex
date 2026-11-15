# Runbook: EvalRecallBelowBaseline

**Meaning.** The latest nightly retrieval evaluation put reranked Recall@10 below 0.90, the floor set from the
first measured baseline (0.956, 95 % CI 0.895–1.00). Answers will miss evidence more often.

**First five minutes.**
1. Open the newest report in `eval/reports/*-retrieval.md`. Read the "Regression check" section: is the drop
   statistically significant (paired test), or within noise?
2. Compare the per-type table: did one question type (content / relationship) fall, or all of them?
3. `git log` since the previous report: look for changes to chunking, the embedding model, the reranker, retrieval SQL
   or the corpus.

**Likely causes and fixes.**
| Cause | How to tell | Fix |
|---|---|---|
| Embedding model or revision changed | `CORTEX_EMBEDDING_*` differs from the ADR | Revert, or re-embed everything (never mix vectors) |
| Chunking changed | `chunking_version` differs between documents | Re-ingest the corpus with one version |
| Filtered HNSW starving results | dense p50 latency unchanged but recall down for small tenants | Check `hnsw.iterative_scan` is set; run `pytest tests/integration/test_filtered_hnsw.py` |
| Corpus changed | document count differs | Re-validate labels: `python eval/validate_set.py` |

**Done when** a new report shows no significant drop against the previous one.
