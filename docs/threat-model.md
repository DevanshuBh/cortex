# CORTEX threat model

Method: STRIDE over the data flows in `docs/design.md` §7. Each threat names its mitigation and the test that
proves it, so a reviewer can check claims instead of trusting them.

## Assets
Tenant documents and passages · answers and question history · the knowledge graph · access tokens · the host
running sandboxed code · model/compute budget.

## Trust boundaries
Browser ↔ API (internet) · API/worker ↔ data stores (internal network) · worker ↔ model server · worker ↔
sandbox-runner ↔ Docker daemon · **retrieved document text ↔ model prompt** (untrusted data entering instructions).

## Threats

| # | Threat (STRIDE) | Mitigation | Evidence |
|---|---|---|---|
| T1 | Tenant A reads tenant B's passages (I) | tenant only from verified JWT; every query filters `tenant_id`; forced RLS with a non-owner app role; transaction-local tenant setting | `test_rls.py` (incl. owner-bypass and pooled-`SET` leak demos), `test_api_flow.py` 404s |
| T2 | Cross-tenant leak through the graph (I) | MERGE on `(tenant_id, canonical_name)` + uniqueness constraint; tenant filter on every node and edge | `test_neo4j_isolation.py` |
| T3 | Small tenant gets wrong/empty results from filtered ANN, or results out of order (I/D) | `hnsw.iterative_scan = relaxed_order`; strict re-sort with `+ 0` | `test_filtered_hnsw.py` |
| T4 | Forged or replayed token (S) | RS256/ES256 via JWKS, issuer, audience, expiry required; tokens kept in memory in the browser | `test_auth.py` |
| T5 | Prompt injection in a document changes behaviour (T/E) | documents enter prompts as escaped, delimited data; tool allow-lists enforced in code; Analyst has no tools | `test_supervisor.py::test_tool_allow_lists…`, adversarial eval set |
| T6 | Exfiltration via Markdown image or link in an answer (I) | server strips images/remote links; UI renders no images and no raw HTML; CSP `img-src 'self'` | `test_prompting.py`, `Markdown.test.tsx`, adversarial `a01` |
| T7 | XSS through model output (T) | react-markdown without raw HTML, `urlTransform` drops `javascript:`; strict CSP | `Markdown.test.tsx` |
| T8 | Sandbox escape: network, secrets, host, resources (E/D) | throwaway container: no network, read-only root, nobody, no capabilities, pid/memory/CPU/time/output limits; runner-only Docker access | `tests/sandbox/test_escape.py` (11 tests) |
| T9 | Docker socket abuse via the runner (E) | runner accepts only code text with a shared token, fixed image and flags, internal network only, no published port | code review of `sandbox/runner/runner.py` (stdlib only, ~150 lines) |
| T10 | Runaway agent burns compute (D) | step, token, wall-clock budgets; no-progress and repeated-call stops; extractive fallback | loop tests in `test_supervisor.py` |
| T11 | Duplicate side effects after a crash (T) | idempotent tasks; one answer per task; tool-effect ledger | `test_idempotency.py` |
| T12 | Hallucinated answers (T) | cite-or-refuse prompt; citations to unknown evidence dropped; uncited answers become "not found" | `test_prompting.py`, answer eval (no-answer accuracy) |
| T13 | Oversized or malicious uploads (D) | type allow-list, 25 MB limit on API and presigned path, parser errors isolated per document | `test_api_flow.py` |
| T14 | Secrets in Git (I) | config from environment; SOPS + age for k8s secrets; Trivy secret scan in CI | `.github/workflows/ci.yml` |
| T15 | Model provider sees confidential data (I) | confidential tenants pinned to local models; Bedrock residency ADR | `llm.py::resolve`, ADR 0011 |

## Residual risks
- The runner's Docker socket is root-equivalent on the host; gVisor (k3s) or Fargate (AWS) removes this.
- Small local models follow injected instructions more readily than large ones; defence is structural (tools,
  rendering, stripping), not reliant on the model refusing.
- The development Keycloak realm enables the password grant for the CLI client; production disables it.
