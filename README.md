# CORTEX

**[Live demo →](https://devanshubh.github.io/cortex/)** (static front end; replays answers recorded from the real system)

**A multi-tenant research assistant that answers questions over a team's documents and cites the exact passage behind
every claim.** Hybrid retrieval (Postgres full-text + pgvector, fused with Reciprocal Rank Fusion and reranked by a
cross-encoder), a per-tenant knowledge graph for relationship questions, and a small team of budgeted agents —
measured on a labelled evaluation set, with confidence intervals on every number.

Runs entirely on free infrastructure: local open-weight models on a laptop GPU, an Oracle Always Free VM for the
always-on deployment, and Terraform for a short AWS proof window.

## What it does

- **Cited answers.** Every sentence ends with the evidence it came from; one click opens the passage (PDF page with the
  passage highlighted, or the text in context). Answers without valid citations are refused: *"Not found in your
  documents."*
- **Relationship questions.** Entities and relations are extracted into Neo4j per tenant; "what manages the Pods a
  Deployment creates?" walks a bounded, tenant-filtered path and cites the passages behind each edge.
- **Agents with budgets.** A LangGraph supervisor routes each question, a Researcher retrieves, a Coder runs
  calculations in a locked-down sandbox, an Analyst writes the answer. Step, token and time budgets plus
  no-progress and repeated-call detection guarantee every run ends.
- **Multi-tenant by construction.** The tenant comes only from the verified token; every query filters on it; Postgres
  row-level security is forced and tested against the two classic mistakes; graph merges key on tenant + name.
- **Live research workspace.** Streaming answers (resumable after a dropped connection), live agent activity with a
  budget meter, a graph explorer, a document library with direct-to-storage uploads, and a quality and cost dashboard.

## Measured results

From `benchmarks.md` (57 answerable labelled questions, 95 % bootstrap intervals):

| Retrieval | Recall@1 | Recall@10 | MRR |
|---|---|---|---|
| dense (pgvector) | 36.8 % | 93.0 % [86.0, 98.2] | 0.583 |
| fused + cross-encoder rerank | **52.6 %** | **95.6 %** [89.5, 100] | **0.693** |

The reranker lifts the top result substantially; at Recall@10 the gain over dense is within noise at this sample size —
reported as such. Correctness evidence: 95 backend tests (unit, integration against real Postgres/Redis/Neo4j, sandbox
escape), 11 front-end unit tests, and end-to-end journeys on desktop and phone with zero WCAG 2.2 AA violations.

## Architecture

```
browser ──► FastAPI ──► Celery (Redis) ──► worker ── LangGraph supervisor
   ▲  SSE      │                             │        ├─ Researcher: FTS + pgvector → RRF → rerank · Cypher paths
   └── Redis Streams (resume on Last-Event-ID) ┤        ├─ Coder: sandbox-runner → throwaway container (no network)
                │                             │        └─ Analyst: cited answer, grounding gate
   presigned PUT ► S3 API (SeaweedFS / S3)     ├─► PostgreSQL + pgvector (RLS)   ├─► Neo4j (per-tenant graph)
                                              └─► Ollama (local) / Bedrock (AWS) behind one ModelClient
```

Design: [`docs/design.md`](docs/design.md) · decisions: [`docs/adr/`](docs/adr) · threat model:
[`docs/threat-model.md`](docs/threat-model.md) · runbooks: [`docs/runbooks/`](docs/runbooks).

## Run it locally

Requirements: Docker Desktop (12 GB for WSL 2 recommended), an NVIDIA GPU for local models (CPU works, slowly),
Python 3.13 with `uv`, Node 22.

```bash
docker compose --profile gpu up -d --build            # stack + local model server
docker compose exec ollama ollama pull qwen3.5:2b      # small tier
docker compose exec ollama ollama pull qwen3.5:9b      # large tier
docker compose run --rm -v "$PWD/corpus:/corpus:ro" migrate sh -c \
  "python -m cortex.cli tenant k8s-docs && python -m cortex.cli ingest-dir k8s-docs /corpus/kubernetes"
docker compose run --rm migrate python -m cortex.cli extract k8s-docs   # knowledge graph (≈ 2–3 h on a laptop GPU)
docker compose run --rm migrate python -m cortex.cli ask k8s-docs "What does a Deployment manage?" --stream

cd web && npm ci && npm run dev                       # http://localhost:3000 — sign in as alice / alice-dev-password
```

Demo users (development realm only): `alice` (admin) and `bob` (member) in tenant `k8s-docs`; `carol` (admin) in `acme`.

## Evaluate

```bash
python eval/validate_set.py                                              # every label quote exists in the corpus
docker compose run --rm -v "$PWD/eval:/eval" -w /eval -e PYTHONPATH=/eval migrate \
  python -m cortex_eval retrieval --tenant k8s-docs                      # ablation + regression check
...  python -m cortex_eval answers --tenant k8s-docs --judge             # full answers, judge, adversarial set
...  python -m cortex_eval router                                         # router accuracy + confusion matrices
```

Reports land in `eval/reports/` and in the dashboard. The nightly CI job reruns the retrieval evaluation and fails on a
statistically significant drop.

## Test

```bash
cd backend && uv run ruff check . && uv run mypy && uv run pytest     # unit + integration (Docker) + sandbox
cd web && npm run lint && npm run typecheck && npm test && npm run build && npx playwright test
```

## Deploy for free

- **Always-on**: `deploy/terraform/oci` creates an Oracle Always Free A1 VM with k3s, gVisor, KEDA and cert-manager;
  `kubectl apply -k deploy/k8s` deploys the stack (secrets via SOPS + age). Images are multi-arch on GHCR.
- **Demo UI**: GitHub Pages (static export in demo mode), published by `.github/workflows/pages.yml` on every push to `main`.
- **AWS proof window**: `deploy/terraform/aws` — ECS Fargate, RDS + pgvector, ElastiCache, S3 + CloudFront, Bedrock
  through IAM, the sandbox as a role-less Fargate task with egress only to VPC endpoints. Apply, measure, destroy.

## Repository

| Path | Contents |
|---|---|
| `backend/` | FastAPI API, Celery workers, retrieval, graph, agents, migrations, tests |
| `web/` | Next.js 16 research workspace, unit and Playwright tests |
| `eval/` | labelled questions, adversarial documents, router labels, harness, reports |
| `sandbox/` | sandbox image and runner |
| `deploy/` | Compose configs, k3s manifests, Terraform (OCI, AWS), observability |
| `corpus/` | the Kubernetes documentation corpus (CC BY 4.0, see `corpus/NOTICE.md`) |
| `docs/` | design, ADRs, threat model, runbooks |

## Licence

Code: MIT. Corpus: CC BY 4.0, © The Kubernetes Authors (see `corpus/NOTICE.md`).
