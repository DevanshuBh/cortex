# CORTEX — design document

Status: accepted · Last updated: 2026-11-14

## 1. Problem

Teams keep their knowledge in documents nobody has time to read end to end. Keyword search finds words, not
answers; a chat model answers fluently but invents things. CORTEX answers questions over a team's own documents
and **cites the exact passage behind every claim**, so a reader can check any answer in two clicks. It also
answers *relationship* questions ("what manages the Pods a Deployment creates?") that plain passage search handles
badly, and it says "not found in your documents" instead of guessing.

## 2. Users

| User | Needs |
|---|---|
| Team member | Upload documents, ask questions, follow citations to the passage |
| Team admin | Manage the team's documents; see usage and cost |
| Operator | Watch quality, cost and queue health; run the nightly evaluation |

## 3. Requirements

### Functional
1. Upload PDF, Markdown, HTML and text documents into a tenant; see ingestion status per document.
2. Ask a question; receive a streamed answer whose every claim cites chunk ids; open the cited passage.
3. Relationship questions use a per-tenant knowledge graph.
4. Multi-step questions are handled by agents (Researcher, Analyst, Coder) within a step and token budget.
5. Admins see cost per query, routing mix and evaluation history.

### Non-functional (targets; measured values live in `benchmarks.md`)
| Property | Target | How measured |
|---|---|---|
| Tenant isolation | zero cross-tenant rows, nodes, cache hits | negative tests in CI (Postgres, Neo4j, cache) |
| Grounding | every answer cites; no-answer questions return "not found" | eval harness, faithfulness grading |
| Retrieval quality | Recall@10 above the dense-only baseline, outside the bootstrap CI | ablation table |
| Upload acknowledgement | p95 < 300 ms (file goes straight to object storage) | k6 |
| Time to first token | p95 < 6 s on the laptop GPU | harness latency |
| Agent termination | 100 % of runs end within budget | loop tests |
| Durability | a killed worker's task is redelivered, side effects run once | chaos test |
| Cost | tokens and cost recorded per call and per query | `llm_calls` table, dashboard |

## 4. Estimates

The local deployment is small; the numbers below are for the reference design in guide §7.2 and drive sizing.

| Quantity | Working | Result |
|---|---|---|
| Chunks | 50 tenants × 2,000 docs × 30 chunks | 3 M |
| Vector storage (float32) | 3 M × 384 × 4 B | ≈ 4.6 GB + HNSW overhead |
| halfvec / binary | ÷ 2 / ÷ 32 | ≈ 2.3 GB / ≈ 144 MB (binary needs re-scoring) |
| Tokens per day | 20 k questions × 6 calls × 3.5 k tokens | ≈ 420 M |
| Concurrent tasks at peak | Little's law: 5 q/s × 20 s | ≈ 100 → worker and model quotas |

Model tokens, not servers, dominate cost; answer latency drives concurrency. Routing, caching and fewer agent
steps are the cost levers.

## 5. API (v1)

| Method & path | Purpose | Notes |
|---|---|---|
| `POST /v1/documents` | Register a document and get a presigned upload URL | returns `document_id`, `upload_url` |
| `POST /v1/documents/{id}/complete` | Mark upload done; queue ingestion | idempotent; returns `task_id` |
| `POST /v1/documents:upload` | Small-file upload through the API (CLI, tests) | multipart; same ingestion task |
| `GET /v1/documents` · `DELETE /v1/documents/{id}` | List / delete | delete removes chunks, vectors, graph facts, object |
| `POST /v1/ask` | Queue a question | `Idempotency-Key` header supported; returns `task_id` |
| `GET /v1/tasks/{id}` | Task status and result | |
| `GET /v1/tasks/{id}/events` | SSE stream of progress and tokens | resumes from `Last-Event-ID` |
| `POST /v1/tasks/{id}/cancel` | Stop a running answer | revokes the Celery task |
| `POST /v1/answers/{id}/feedback` | Thumbs up/down | stored for evaluation |
| `GET /v1/chunks/{id}` | A cited passage with its document position | tenant-scoped |
| `GET /v1/graph/answer/{task_id}` | Paths used by a relationship answer | |
| `GET /v1/admin/usage` · `GET /v1/admin/eval-runs` | Cost and evaluation history | admin role |

Errors use RFC 9457 problem details. The tenant comes **only** from the verified JWT (`tenant_id` claim).

## 6. Data model

**PostgreSQL** (owner role runs migrations; the app role is not the owner and every table has
`FORCE ROW LEVEL SECURITY`):

- `documents(tenant_id, id, title, source_uri, mime, status, error, content_hash, chunking_version, created_at)`
- `chunks(tenant_id, id, document_id, position, heading_path, text, token_count, content_hash,
  chunking_version, embedding vector(384), tsv tsvector GENERATED)` — HNSW (cosine) + GIN indexes
- `tasks(tenant_id, id, kind, status, idempotency_key, input, result, error, created_at, updated_at)`
- `llm_calls(tenant_id, task_id, step, model, tier, prompt_version, input_tokens, output_tokens, cost_usd,
  latency_ms, created_at)`
- `answers(tenant_id, task_id, question, answer, evidence, route, partial, created_at)`, `feedback(...)`
- `tool_effects(run_id, step, tool, result)` — idempotency ledger for agent side effects
- `eval_runs(...)` — summary rows written by the harness

Invariants: every row has a `tenant_id`; a chunk's embedding comes from exactly one pinned model
(`embedding_model` recorded per index); a task id produces at most one answer row.

**Neo4j**: `(:Entity {tenant_id, canonical_name, name, type})`,
`(:Chunk {tenant_id, chunk_id, document_id})`, `(:Entity)-[:REL {tenant_id, type, chunk_ids}]->(:Entity)`,
`(:Entity)-[:MENTIONED_IN {tenant_id}]->(:Chunk)`. Uniqueness constraint on
`(Entity.tenant_id, Entity.canonical_name)`; every `MERGE` and `MATCH` includes `tenant_id`.

**Redis**: Celery broker (non-cluster mode); `task:{id}:events` stream per task (`MAXLEN ~ 5000`, TTL 1 h).

**Object storage** (S3 API; SeaweedFS locally): `tenants/{tenant_id}/documents/{document_id}/{filename}`.

## 7. High-level design

```
 browser ──HTTPS──► api (FastAPI) ──enqueue──► Redis (Celery broker) ──► worker (Celery)
    │  ▲                │  ▲                                              │
    │  └──── SSE ◄──────┘  └──── XREAD task:{id}:events ◄──── XADD ───────┤
    │                   │                                                 ├─► Postgres (chunks, vectors, FTS, RLS)
    └─presigned PUT──► object storage (S3 API)  ◄──── GET ────────────────┤
                                                                          ├─► Neo4j (entity graph)
                                                                          ├─► model server (Ollama / Bedrock)
                                                                          └─► sandbox-runner ─► sandbox container
```

Synchronous edges: browser→api, api→Postgres for reads. Everything slow (ingestion, answering) is asynchronous
through Celery; progress flows back through a Redis Stream so a reconnecting browser misses nothing.

**Question flow.** `POST /v1/ask` stores a task and enqueues it → the worker runs the LangGraph supervisor →
the router labels the question content / relationship / both → the Researcher runs hybrid retrieval
(FTS + pgvector, RRF k = 60, cross-encoder rerank) and/or bounded Cypher → the Coder may run code in the sandbox →
the Analyst writes the answer citing evidence ids → a citation check drops unsupported ids and remote images →
the answer row is written once, keyed by task id.

## 8. Deep dives

### 8.1 Tenant isolation (three layers)
1. **Application:** every repository, retriever and Cypher query takes a required `tenant_id`; the API takes it only
   from the token.
2. **Database:** RLS policies on every table. Pitfalls handled: table owners bypass RLS → the app connects as a
   non-owner role and tables use `FORCE ROW LEVEL SECURITY`; a plain `SET` on a pooled connection leaks into the
   next request → the tenant is set with `set_config('app.tenant_id', $1, true)` (transaction-local) at the start
   of every transaction. Both mistakes have tests that demonstrate the leak, then the fix.
3. **Graph:** `MERGE` keys on `(tenant_id, canonical_name)`, never the name alone; traversal filters every node
   and relationship on `tenant_id`.

### 8.2 Filtered vector search
pgvector applies `WHERE tenant_id = …` after the HNSW scan; with `ef_search = 40` a tenant holding 10 % of rows
gets about 4 results instead of 10. Every dense query runs with `hnsw.iterative_scan = relaxed_order` (pgvector
0.8+) and re-sorts the materialised result. A test seeds one tenant with 1 % of the chunks and requires k results.

### 8.3 Chunking and embeddings
Structure-aware chunks (headings, then paragraphs, then sentences) sized in the **embedding model's own
tokens**, at most 400 of bge-small-en-v1.5's 512, with ~15 % overlap. Any chunk that would be truncated is
logged and split. Changing the model is a re-embedding migration (shadow index, evaluate, switch).

### 8.4 Resumable streaming and at-least-once tasks
Celery runs with `acks_late`, `worker_prefetch_multiplier = 1`, a Redis `visibility_timeout` above the longest
hard time limit, and soft/hard limits per task type. A redelivered task re-runs, so every side effect is
idempotent: chunk writes replace by `(document_id, chunking_version)` in one transaction; the answer row is
unique per task; agent tool effects are recorded in `tool_effects(run_id, step)` and skipped if present.
Tokens go to a Redis Stream; SSE event ids are stream ids; the browser resumes with `Last-Event-ID`.

### 8.5 Agent termination
The supervisor graph stops on: step budget, token budget, N steps with no new evidence, a repeated identical tool
call, or a wall-clock limit. It then returns the best answer so far marked `partial`. Termination is tested with
scripted looping agents; a legitimate long task is tested not to stop early.

### 8.6 Sandbox
Coder code runs in a separate image with `--network none --read-only --tmpfs /tmp:size=64m --pids-limit 64
--memory 256m --cpus 0.5 --cap-drop ALL --security-opt no-new-privileges --user 65534`, a 10 s wall-clock
kill and 64 KB output cap. A small `sandbox-runner` service owns the Docker socket and accepts only code text;
the worker never talks to Docker. On k3s the sandbox runs under gVisor (`runtimeClassName: gvisor`); on AWS as a
Fargate task with no task role in a subnet with no route out except VPC endpoints for ECR, Logs and S3.

### 8.7 Prompt injection and exfiltration
Retrieved text enters prompts as escaped, delimited data; each agent has a code-enforced tool allow-list; the
answer post-processor removes remote image/link syntax; the UI renders Markdown with no raw HTML and no remote
images, under `img-src 'self'`. Adversarial documents and exfiltration questions are part of the evaluation set.

## 9. Failure modes

| Edge | Failure | Effect | Detection | Recovery |
|---|---|---|---|---|
| api → Redis | broker down | ask/upload return 503 | health check, error-rate alert | retry with backoff; queue resumes |
| worker | killed mid-task | task redelivered after visibility timeout | queue age metric | idempotent side effects; stream resumes |
| worker → model | slow / throttled | answer latency rises | p95, throttling counter | budget + timeout → partial answer |
| worker → Postgres | down | task fails, retried | task failure rate | Celery retry with backoff |
| worker → Neo4j | down | relationship route degrades | error counter | fall back to hybrid retrieval, flag in answer |
| SSE | browser disconnects | missed tokens | — | `Last-Event-ID` resume from stream |
| ingestion | parser fails on a file | document `failed` with reason | status + alert on failure rate | user re-uploads; others unaffected |
| extraction | model emits invalid JSON | chunk skipped for graph | extraction failure rate metric | logged; retrieval still works |
| eval | quality regression | — | nightly eval below baseline → alert | revert; runbook |

## 10. Trade-offs and evolution

- **Postgres for vectors and FTS** instead of a dedicated vector DB: one store, transactional with chunk rows, RLS.
  At ~10× (30 M chunks) move to halfvec or partition by tenant; at ~100×, a dedicated ANN service.
- **Neo4j Community** single database → property-based tenancy. Enterprise multi-database would give hard isolation.
- **RRF** instead of score blending: dense and sparse scores live on different scales; rank fusion needs no tuning.
- **Local models** (Ollama) on the free path; Bedrock on AWS behind the same `ModelClient` interface.
- **Celery + Redis** instead of a workflow engine: simple and well understood; durability of agent runs comes from
  checkpoints in Postgres (staff step S.5) rather than the broker.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Hallucination | cite-or-refuse prompt, citation check, faithfulness eval with calibrated judge |
| Prompt injection | delimited data, tool allow-lists, image stripping, red-team evals |
| Cost runaway | per-request step/token caps, per-tenant budgets, cost alerts |
| Cross-tenant leakage | three isolation layers + negative tests in every store |
| Weak local models | routing and evaluation make the quality/cost trade-off explicit |
