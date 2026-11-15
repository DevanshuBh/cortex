# Runbook: AnswerLatencyHigh

**Meaning.** p95 time to finish an answer has been above 60 s for 10 minutes.

**First five minutes.**
1. Grafana "Retrieval stage latency p95": is retrieval slow (Postgres, reranker) or the model?
2. Open one slow task's trace in Jaeger (service `cortex-worker`): which span dominates?
3. `ollama ps` inside the ollama container: are both models loaded, or swapping in and out of GPU memory?

**Fixes.**
- Model swapping (small and large tiers do not both fit in 8 GB VRAM) → set `OLLAMA_MAX_LOADED_MODELS=1` and
  route more steps to one tier, or use a smaller large model.
- Reranker slow under load → it runs on CPU in each worker; lower `CORTEX_RERANK_CANDIDATES` (default 20).
- Agents taking many steps → check "Loop-guard stops"; tighten `CORTEX_AGENT_MAX_STEPS`.
