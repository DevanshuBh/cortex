# ADR 0005 — Free local models behind one ModelClient; hosted and Bedrock as configuration

Status: accepted · 2026-11-14

## Context
The project must cost nothing. Quality depends on the models, and cost/quality routing (guide step 4.4) needs at
least two tiers.

## Decision
- Default provider: **Ollama** on the laptop GPU. Small tier `qwen3.5:2b` (routing, extraction, planning), large
  tier `qwen3.5:9b` (answers, code), judge `gemma4:e4b` (a different model family than the answerer, to limit
  self-preference bias). `think: false` and a fixed seed for reproducibility.
- Optional: any **OpenAI-compatible** endpoint (Groq, Gemini, OpenRouter free tiers) for the large tier only.
  Tenants flagged *confidential* are always forced back to local models.
- **Amazon Bedrock** (Converse API, IAM role, no stored key) for the AWS proof window; see ADR 0011 on data residency.
- Every call is logged to `llm_calls` with tenant, task, step, prompt version, tokens, latency and notional cost.

## Consequences
Weaker local models make routing, grounding checks and evaluation matter more. On 8 GB of VRAM the two tiers
cannot both stay loaded; Ollama swaps them, which shows up in answer latency (runbook: answer-latency).
