# ADR 0011 — Bedrock in ap-south-1 and data residency

Status: proposed (for the AWS proof window) · 2026-11-15

## Context
Some Bedrock models in ap-south-1 (Mumbai) are only reachable through **cross-region inference profiles**, which may
process requests in other APAC regions. For a tenant whose documents must stay in India, that is a residency breach
even though the API call is made in Mumbai.

## Decision
- Before the AWS window, list the models offered *in-region* in ap-south-1 and choose tiers only from those for
  tenants flagged `confidential` (they already never leave local models on the free path).
- Non-confidential tenants may use a cross-region profile; the profile id is recorded per call in `llm_calls.model`.
- If no in-region model fits, confidential tenants stay on self-hosted models.

## Consequences
Model choice becomes per-tenant policy, not a global setting — the `confidential` flag in `tenants` carries it.
