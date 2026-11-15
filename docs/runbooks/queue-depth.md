# Runbook: QueueDepthRising

**Meaning.** More than 20 questions are waiting in the `ask` queue and the backlog has grown for 5 minutes.
Users see "Starting…" for a long time.

**First five minutes.**
1. `docker compose ps worker-ask` (or `kubectl get pods -l app=worker-ask`): are workers running and healthy?
2. Worker logs: are tasks finishing, or stuck on model calls (`ollama` slow / GPU busy)?
3. Grafana "Answer time p50 / p95" and "Model calls": is the model the bottleneck?

**Fixes.**
- Workers down or crash-looping → restart; check the last error in the logs.
- Model saturated (one GPU) → reduce concurrency, or route the large tier to a free hosted endpoint
  (`CORTEX_MODEL_PROVIDER_LARGE=openai_compat`) for non-confidential tenants.
- Burst of traffic → scale `worker-ask` (KEDA does this on k3s from the same metric).

Little's law sizing: concurrent tasks ≈ arrival rate × answer time. At 20 s per answer, each extra worker slot
absorbs about 3 questions a minute.
