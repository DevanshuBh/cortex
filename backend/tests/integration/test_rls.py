"""Tenant isolation in Postgres, including the two RLS mistakes from guide step 5.1 — shown, then fixed."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from cortex.db import repo
from cortex.db.session import get_engine, tenant_session

pytestmark = pytest.mark.integration


def _doc(tenant: str) -> str:
    with tenant_session(tenant) as db:
        return repo.create_document(
            db,
            tenant,
            title="secret plan",
            filename="plan.md",
            mime="text/markdown",
            object_key=f"tenants/{tenant}/x",
            status="ready",
        )


def test_another_tenants_rows_are_invisible_even_without_the_app_filter(
    tenant: str, other_tenant: str
) -> None:
    doc = _doc(tenant)
    with tenant_session(other_tenant) as db:
        assert repo.get_document(db, other_tenant, doc) is None
        # RLS is the second layer: a query that forgets the tenant filter still sees nothing.
        n = db.execute(
            text("SELECT count(*) FROM documents WHERE id = CAST(:id AS uuid)"), {"id": doc}
        ).scalar()
        assert n == 0
    with tenant_session(tenant) as db:
        assert repo.get_document(db, tenant, doc) is not None


def test_writing_a_row_for_another_tenant_is_rejected(tenant: str, other_tenant: str) -> None:
    with pytest.raises(DBAPIError, match="row-level security"), tenant_session(other_tenant) as db:
        repo.create_document(
            db, tenant, title="x", filename="x.md", mime="text/markdown", object_key="k", status="ready"
        )


def test_unscoped_connection_sees_nothing(tenant: str) -> None:
    _doc(tenant)
    with get_engine().connect() as c:
        assert c.execute(text("SELECT count(*) FROM documents")).scalar() == 0


def test_table_owner_bypasses_rls_unless_forced(pg: dict[str, str]) -> None:
    """Mistake 1: owners bypass RLS. Demonstrated on a scratch table owned by the owner role."""
    owner = create_engine(pg["owner"])
    with owner.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS rls_demo"))
        c.execute(text("CREATE TABLE rls_demo (tenant_id text, v int)"))
        c.execute(text("INSERT INTO rls_demo VALUES ('a', 1), ('b', 2)"))
        c.execute(text("ALTER TABLE rls_demo ENABLE ROW LEVEL SECURITY"))
        c.execute(
            text("CREATE POLICY p ON rls_demo USING (tenant_id = current_setting('app.tenant_id', true))")
        )
    with owner.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', 'a', true)"))
        assert c.execute(text("SELECT count(*) FROM rls_demo")).scalar() == 2, "owner sees every tenant"
    with owner.begin() as c:
        c.execute(text("ALTER TABLE rls_demo FORCE ROW LEVEL SECURITY"))
    with owner.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', 'a', true)"))
        assert c.execute(text("SELECT count(*) FROM rls_demo")).scalar() == 1, (
            "FORCE applies RLS to the owner"
        )
    with owner.begin() as c:
        c.execute(text("DROP TABLE rls_demo"))
    owner.dispose()


def test_plain_set_leaks_through_the_pool_but_transaction_local_set_does_not(
    pg: dict[str, str],
    tenant: str,
) -> None:
    """Mistake 2: ``SET`` on a pooled connection survives into the next request."""
    _doc(tenant)
    engine = create_engine(pg["app"], pool_size=1, max_overflow=0)
    with engine.connect() as c:  # request 1 sets the tenant the wrong way
        c.execute(text(f"SET app.tenant_id = '{tenant}'"))
        c.commit()
    with engine.connect() as c:  # request 2, same pooled connection, never set a tenant
        leaked = c.execute(text("SELECT count(*) FROM documents")).scalar()
    assert leaked == 1, "the previous request's tenant leaked into this one"
    engine.dispose()

    engine = create_engine(pg["app"], pool_size=1, max_overflow=0)
    with engine.begin() as c:  # the right way: transaction-local, what tenant_session does
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
        assert c.execute(text("SELECT count(*) FROM documents")).scalar() == 1
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM documents")).scalar() == 0
    engine.dispose()


def test_tenant_session_leaves_no_tenant_on_the_pooled_connection(tenant: str) -> None:
    _doc(tenant)
    with tenant_session(tenant) as db:
        assert db.execute(text("SELECT count(*) FROM documents")).scalar() == 1
    for _ in range(3):  # whichever pooled connection we get back, it carries no tenant
        with get_engine().connect() as c:
            assert (
                c.execute(text("SELECT coalesce(current_setting('app.tenant_id', true), '')")).scalar() == ""
            )


def test_invalid_tenant_ids_are_rejected_before_reaching_sql() -> None:
    with pytest.raises(ValueError, match="invalid tenant"), tenant_session("a'; DROP TABLE chunks; --"):
        pass
