# Runbook: ModelErrorsOrThrottling

**Meaning.** More than 5 % of model calls failed or were throttled over 5 minutes. Answers fail with
"The language model is unavailable".

**First five minutes.**
1. `cortex_llm_errors_total` by `throttled`: throttling (429/503) or hard errors?
2. Local: `docker compose logs ollama --tail 50` — out of GPU memory? model missing (`ollama list`)?
3. Hosted endpoint (if configured): check its status page and your free-tier quota.

**Fixes.**
- Model not pulled → `docker compose exec ollama ollama pull qwen3.5:9b` (and `qwen3.5:2b`, `gemma4:e4b`).
- GPU out of memory → restart ollama; keep one model loaded at a time.
- Hosted quota exhausted → unset `CORTEX_MODEL_PROVIDER_LARGE` to fall back to local models.

Ask tasks retry once on throttling; extraction failures leave passages searchable (only graph facts are missing).
