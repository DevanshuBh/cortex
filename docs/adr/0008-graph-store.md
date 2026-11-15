# ADR 0008 — Neo4j Community, one database, property-based tenancy

Status: accepted · 2026-11-14

## Decision
Neo4j Community Edition (self-hosted in Compose/k3s; on AWS on EC2 rather than Aura, to stay inside free credits).
Community has one user database, so tenancy is a `tenant_id` property on every node and relationship:
- `MERGE` keys on `(tenant_id, canonical_name)` with a matching uniqueness constraint — never the name alone
  (`test_merge_on_name_alone_would_leak` shows two tenants' "Acme Corp" collapsing into one node);
- every traversal filters every node *and* relationship on `tenant_id`, at most 3 hops, always with `LIMIT`.

## Alternatives
Neo4j Enterprise / Aura with a database per tenant (hard isolation, paid); relationships in Postgres tables with
recursive CTEs (one store fewer; weaker path queries). Revisit at ~100 tenants or when a customer requires
physical isolation.
