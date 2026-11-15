"""Typed configuration. Every value comes from the environment (prefix ``CORTEX_``) or ``.env``."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CORTEX_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    # PostgreSQL: the app connects as a NON-owner role so row-level security applies (design §8.1).
    database_url: str = "postgresql+psycopg://cortex_app:cortex_app@localhost:5432/cortex"
    # Migrations run as the owner role.
    migration_database_url: str = "postgresql+psycopg://cortex_owner:cortex_owner@localhost:5432/cortex"
    db_pool_size: int = 10

    redis_url: str = "redis://localhost:6379/0"
    # Celery's Redis broker needs a non-cluster-mode Redis. visibility_timeout must exceed every hard time
    # limit, or a long task is redelivered while still running (checked at worker start).
    broker_url: str = "redis://localhost:6379/1"
    celery_visibility_timeout: int = 3600
    ask_soft_time_limit: int = 300
    ask_time_limit: int = 330
    ingest_soft_time_limit: int = 600
    ingest_time_limit: int = 660
    extract_soft_time_limit: int = 2400
    extract_time_limit: int = 2500
    worker_metrics_port: int = 9100
    stream_maxlen: int = 5000
    stream_ttl_seconds: int = 3600

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("cortex-neo4j")

    # Object storage, S3 API only (SeaweedFS locally, S3 on AWS).
    s3_endpoint_url: str | None = "http://localhost:8333"
    # Endpoint the *browser* uses for presigned URLs (differs from the in-cluster one in Compose).
    s3_public_endpoint_url: str | None = "http://localhost:8333"
    s3_region: str = "us-east-1"
    s3_bucket: str = "cortex-documents"
    s3_access_key: SecretStr = SecretStr("cortex")
    s3_secret_key: SecretStr = SecretStr("cortex-secret")
    max_upload_bytes: int = 25 * 1024 * 1024

    # Auth: tenant_id only ever comes from a verified token.
    oidc_issuer: str = "http://localhost:8080/realms/cortex"
    oidc_jwks_url: str = "http://localhost:8080/realms/cortex/protocol/openid-connect/certs"
    oidc_audience: str = "cortex-api"
    tenant_claim: str = "tenant_id"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Embeddings — pinned; changing it is a re-embedding migration (docs/adr/0003).
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    embedding_dim: int = 384
    embedding_max_tokens: int = 512
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "
    chunk_max_tokens: int = 400
    chunk_overlap_tokens: int = 60
    chunking_version: str = "struct-v1"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_revision: str = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
    models_device: str = "cpu"

    # Retrieval
    retrieval_k: int = 10
    rerank_candidates: int = 20
    rerank_top_n: int = 5
    rrf_k: int = 60
    hnsw_ef_search: int = 100

    # Language models behind one ModelClient interface (docs/adr/0005). Default is free and local.
    #   ollama        — local models on the laptop GPU (free, private, no rate limits)
    #   openai_compat — any OpenAI-compatible endpoint, e.g. a free tier of Groq / Gemini / OpenRouter
    #   bedrock       — Amazon Bedrock Converse API, for the AWS proof window only
    #   fake          — deterministic scripted model for tests
    model_provider: Literal["ollama", "openai_compat", "bedrock", "fake"] = "ollama"
    # Provider for the large tier only; None = same as model_provider. Confidential tenants always use ollama.
    model_provider_large: Literal["ollama", "openai_compat", "bedrock"] | None = None
    ollama_url: str = "http://localhost:11434"
    model_small: str = "qwen3.5:2b"
    model_large: str = "qwen3.5:9b"
    model_judge: str = "gemma4:e4b"
    openai_compat_base_url: str = "https://api.groq.com/openai/v1"
    openai_compat_api_key: SecretStr | None = None
    openai_compat_model_large: str = "qwen/qwen3-32b"
    bedrock_region: str = "ap-south-1"
    bedrock_model_small: str = "amazon.nova-micro-v1:0"
    bedrock_model_large: str = "amazon.nova-pro-v1:0"
    # USD per 1M tokens (input, output). Real spend on the free path is zero; these reference list prices give a
    # *notional* cost so routing policies can be compared. Every place that shows the number labels it notional.
    price_small_in: float = 0.035
    price_small_out: float = 0.14
    price_large_in: float = 0.80
    price_large_out: float = 3.20
    llm_timeout_seconds: float = 180.0
    routing_policy: Literal["routed", "small-only", "large-only"] = "routed"

    # Agent budgets (design §8.5)
    agent_max_steps: int = 8
    agent_max_tokens: int = 24_000
    agent_no_progress_steps: int = 2
    agent_wall_clock_seconds: float = 240.0

    # Sandbox
    sandbox_runner_url: str = "http://localhost:8090"
    sandbox_runner_token: SecretStr = SecretStr("dev-sandbox-token")

    # Observability
    otlp_endpoint: str | None = None
    service_name: str = "cortex"


@lru_cache
def get_settings() -> Settings:
    return Settings()
