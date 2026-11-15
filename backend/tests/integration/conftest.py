"""Testcontainers fixtures: real Postgres (pgvector), Redis and Neo4j, configured like production."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from cortex.config import get_settings

ROOT = Path(__file__).resolve().parents[3]
INIT_SQL = ROOT / "deploy" / "postgres" / "init.sql"
PG_IMAGE = "pgvector/pgvector:0.8.7-pg18-trixie"
REDIS_IMAGE = "redis:8.8.4-alpine"
NEO4J_IMAGE = "neo4j:2026.10.2"


def _reset_caches() -> None:
    from cortex.db import session
    from cortex.graph import store
    from cortex.models import llm

    get_settings.cache_clear()
    session.get_engine.cache_clear()
    session._session_factory.cache_clear()
    store.get_driver.cache_clear()
    llm._default_llm.cache_clear()


@pytest.fixture(scope="session")
def pg() -> Iterator[dict[str, str]]:
    from testcontainers.postgres import PostgresContainer

    container = (
        PostgresContainer(PG_IMAGE, username="postgres", password="postgres-test", dbname="postgres")
        .with_volume_mapping(str(INIT_SQL), "/docker-entrypoint-initdb.d/10-init.sql", "ro")
    )
    with container:
        host, port = container.get_container_host_ip(), container.get_exposed_port(5432)
        urls = {
            "app": f"postgresql+psycopg://cortex_app:cortex_app@{host}:{port}/cortex",
            "owner": f"postgresql+psycopg://cortex_owner:cortex_owner@{host}:{port}/cortex",
            "super": f"postgresql+psycopg://postgres:postgres-test@{host}:{port}/cortex",
        }
        os.environ["CORTEX_DATABASE_URL"] = urls["app"]
        os.environ["CORTEX_MIGRATION_DATABASE_URL"] = urls["owner"]
        _reset_caches()
        from cortex.cli import cmd_migrate

        cmd_migrate(None)  # type: ignore[arg-type]
        yield urls
        _reset_caches()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    from testcontainers.redis import RedisContainer

    with RedisContainer(REDIS_IMAGE) as r:
        url = f"redis://{r.get_container_host_ip()}:{r.get_exposed_port(6379)}/0"
        os.environ["CORTEX_REDIS_URL"] = url
        os.environ["CORTEX_BROKER_URL"] = url.replace("/0", "/1")
        _reset_caches()
        from cortex import streaming

        streaming._sync.cache_clear()
        streaming._async_client.cache_clear()
        yield url


@pytest.fixture(scope="session")
def neo4j_driver() -> Iterator[object]:
    from testcontainers.neo4j import Neo4jContainer

    with Neo4jContainer(NEO4J_IMAGE, password="cortex-neo4j-test") as n:
        os.environ["CORTEX_NEO4J_URI"] = n.get_connection_url()
        os.environ["CORTEX_NEO4J_PASSWORD"] = "cortex-neo4j-test"
        _reset_caches()
        driver = n.get_driver()
        from cortex.graph.store import GraphStore

        GraphStore(driver).ensure_schema()
        yield driver
        driver.close()


@pytest.fixture
def tenant(pg: dict[str, str]) -> str:
    from cortex.db.repo import ensure_tenant

    t = f"t-{uuid.uuid4().hex[:10]}"
    ensure_tenant(t)
    return t


@pytest.fixture
def other_tenant(pg: dict[str, str]) -> str:
    from cortex.db.repo import ensure_tenant

    t = f"o-{uuid.uuid4().hex[:10]}"
    ensure_tenant(t)
    return t
