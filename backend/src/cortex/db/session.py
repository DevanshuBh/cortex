"""Database engine and tenant-scoped transactions.

The tenant is set with ``set_config('app.tenant_id', :tenant, true)`` — the ``true`` makes it
transaction-local (equivalent to ``SET LOCAL``), so a pooled connection can never carry one request's tenant
into the next request. See design §8.1 and ``tests/integration/test_rls.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from cortex.config import get_settings

SYSTEM_TENANT = "__system__"


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    return create_engine(
        url or settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=5,
        pool_pre_ping=True,
    )


@lru_cache
def _session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False)


def _validate_tenant(tenant_id: str) -> str:
    if not tenant_id or len(tenant_id) > 64 or not all(c.isalnum() or c in "-_" for c in tenant_id):
        raise ValueError(f"invalid tenant id: {tenant_id!r}")
    return tenant_id


@contextmanager
def tenant_session(tenant_id: str, url: str | None = None) -> Iterator[Session]:
    """One transaction scoped to one tenant. Commits on success, rolls back on error."""
    tenant = _validate_tenant(tenant_id)
    session = _session_factory(url)()
    try:
        with session.begin():
            session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
            yield session
    finally:
        session.close()


def set_search_options(session: Session, ef_search: int) -> None:
    """Transaction-local HNSW options for filtered queries (design §8.2)."""
    session.execute(text("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)"))
    session.execute(text("SELECT set_config('hnsw.ef_search', :ef, true)"), {"ef": str(ef_search)})
