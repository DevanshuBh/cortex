"""Initial schema: tenants, documents, chunks (vectors + FTS), tasks, answers, LLM call log, RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-14
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "documents",
    "chunks",
    "tasks",
    "answers",
    "feedback",
    "llm_calls",
    "tool_effects",
    "audit_log",
]

SCHEMA = """
CREATE TABLE tenants (
    id                   text PRIMARY KEY CHECK (id ~ '^[A-Za-z0-9_-]{1,64}$'),
    name                 text NOT NULL,
    confidential         boolean NOT NULL DEFAULT false,
    monthly_token_budget bigint,
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    tenant_id        text NOT NULL REFERENCES tenants(id),
    id               uuid PRIMARY KEY,
    title            text NOT NULL,
    filename         text NOT NULL,
    mime             text NOT NULL,
    object_key       text NOT NULL,
    size_bytes       bigint,
    status           text NOT NULL CHECK (status IN
                       ('pending_upload','uploaded','parsing','embedding','extracting','ready','failed')),
    error            text,
    content_hash     text,
    chunking_version text,
    chunk_count      integer NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX documents_tenant_created_idx ON documents (tenant_id, created_at DESC);

CREATE TABLE chunks (
    tenant_id        text NOT NULL,
    id               uuid PRIMARY KEY,
    document_id      uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    position         integer NOT NULL,
    heading_path     text NOT NULL DEFAULT '',
    text             text NOT NULL,
    char_start       integer NOT NULL,
    char_end         integer NOT NULL,
    token_count      integer NOT NULL,
    content_hash     text NOT NULL,
    chunking_version text NOT NULL,
    embedding        vector(384),
    tsv              tsvector GENERATED ALWAYS AS (
                       setweight(to_tsvector('english', coalesce(heading_path, '')), 'A') ||
                       setweight(to_tsvector('english', text), 'B')) STORED,
    UNIQUE (document_id, chunking_version, position)
);
CREATE INDEX chunks_tenant_idx ON chunks (tenant_id);
CREATE INDEX chunks_document_idx ON chunks (document_id);
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);

CREATE TABLE tasks (
    tenant_id       text NOT NULL REFERENCES tenants(id),
    id              uuid PRIMARY KEY,
    kind            text NOT NULL CHECK (kind IN ('ingest','ask','extract','delete')),
    status          text NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    idempotency_key text,
    input           jsonb NOT NULL DEFAULT '{}'::jsonb,
    result          jsonb,
    error           text,
    attempts        integer NOT NULL DEFAULT 0,
    created_by      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz,
    UNIQUE (tenant_id, kind, idempotency_key)
);
CREATE INDEX tasks_tenant_created_idx ON tasks (tenant_id, created_at DESC);

CREATE TABLE answers (
    tenant_id     text NOT NULL,
    task_id       uuid PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    question      text NOT NULL,
    answer        text NOT NULL,
    evidence      jsonb NOT NULL DEFAULT '[]'::jsonb,
    route         text NOT NULL,
    partial       boolean NOT NULL DEFAULT false,
    not_found     boolean NOT NULL DEFAULT false,
    steps         integer NOT NULL DEFAULT 0,
    input_tokens  integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    cost_usd      numeric(12, 6) NOT NULL DEFAULT 0,
    latency_ms    integer NOT NULL DEFAULT 0,
    trace         jsonb NOT NULL DEFAULT '[]'::jsonb,
    graph_paths   jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE feedback (
    tenant_id  text NOT NULL,
    id         bigserial PRIMARY KEY,
    task_id    uuid NOT NULL REFERENCES answers(task_id) ON DELETE CASCADE,
    user_id    text NOT NULL,
    rating     smallint NOT NULL CHECK (rating IN (-1, 1)),
    comment    text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (task_id, user_id)
);

CREATE TABLE llm_calls (
    tenant_id      text NOT NULL,
    id             bigserial PRIMARY KEY,
    task_id        uuid,
    step           text NOT NULL,
    provider       text NOT NULL,
    model          text NOT NULL,
    tier           text NOT NULL,
    prompt_version text NOT NULL,
    input_tokens   integer NOT NULL DEFAULT 0,
    output_tokens  integer NOT NULL DEFAULT 0,
    cost_usd       numeric(12, 6) NOT NULL DEFAULT 0,
    latency_ms     integer NOT NULL DEFAULT 0,
    ok             boolean NOT NULL,
    error          text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_calls_tenant_created_idx ON llm_calls (tenant_id, created_at);
CREATE INDEX llm_calls_task_idx ON llm_calls (task_id);

CREATE TABLE tool_effects (
    tenant_id  text NOT NULL,
    run_id     uuid NOT NULL,
    step       integer NOT NULL,
    tool       text NOT NULL,
    args_hash  text NOT NULL,
    result     jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, step, tool, args_hash)
);

CREATE TABLE audit_log (
    tenant_id  text NOT NULL,
    id         bigserial PRIMARY KEY,
    actor      text NOT NULL,
    action     text NOT NULL,
    target     text NOT NULL,
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Operator data, not tenant data: written by the evaluation harness.
CREATE TABLE eval_runs (
    id          bigserial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    git_commit  text,
    name        text NOT NULL,
    config      jsonb NOT NULL,
    metrics     jsonb NOT NULL,
    report_path text
);
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    # Row-level security on every tenant table. FORCE makes it apply to the table owner too; the app role is
    # not the owner anyway. current_setting(..., true) returns NULL when unset, so an unscoped session sees
    # nothing (default deny).
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenants "
        "USING (id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (id = current_setting('app.tenant_id', true))"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cortex_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cortex_app")


def downgrade() -> None:
    for table in [*reversed(TENANT_TABLES), "eval_runs", "tenants"]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
