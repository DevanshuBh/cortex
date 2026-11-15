"""Tenant isolation in Neo4j (guide steps 3.1 and 5.2): two tenants, the same entity name, no crossing."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from cortex.graph.retrieve import GraphRetriever
from cortex.graph.store import EntityIn, GraphStore, RelationIn

pytestmark = pytest.mark.integration


def _load(store: GraphStore, tenant: str, chunk: str, partner: str) -> None:
    store.upsert_chunk_facts(
        tenant, f"doc-{tenant}", chunk,
        [EntityIn("Acme Corp", "organisation"), EntityIn(partner, "organisation")],
        [RelationIn("Acme Corp", "SUPPLIES", partner)],
    )


def test_same_name_in_two_tenants_never_crosses(neo4j_driver: Any) -> None:
    a, b = f"a-{uuid.uuid4().hex[:6]}", f"b-{uuid.uuid4().hex[:6]}"
    store = GraphStore(neo4j_driver)
    _load(store, a, "chunk-a", "Globex")
    _load(store, b, "chunk-b", "Initech")

    with neo4j_driver.session() as s:
        acme = s.run("MATCH (e:Entity {canonical_name: 'acmecorp'}) WHERE e.tenant_id IN [$a, $b] RETURN count(e) AS n",
                     a=a, b=b).single()["n"]
    assert acme == 2, "one Acme node per tenant, not a shared one"

    retriever = GraphRetriever(neo4j_driver, max_hops=3)
    for tenant, own, foreign, partner in ((a, "chunk-a", "chunk-b", "Globex"), (b, "chunk-b", "chunk-a", "Initech")):
        res = retriever.search_paths(tenant, "Who does Acme Corp supply?")
        cited = {c for p in res.paths for c in p.chunk_ids}
        names = {n for p in res.paths for n in p.nodes}
        assert own in cited and foreign not in cited
        assert partner in names and ({"Globex", "Initech"} - {partner}).isdisjoint(names)


def test_merge_on_name_alone_would_leak(neo4j_driver: Any) -> None:
    """The counterexample: MERGE (e:Entity {name: $name}) joins both tenants' Acme into one node."""
    label = f"Leak{uuid.uuid4().hex[:6]}"
    with neo4j_driver.session() as s:
        for tenant, partner in (("x", "Globex"), ("y", "Initech")):
            s.run(f"MERGE (e:{label} {{name: 'Acme Corp'}}) SET e.tenant_id = $t "
                  f"MERGE (p:{label} {{name: $p, tenant_id: $t}}) MERGE (e)-[:SUPPLIES]->(p)", t=tenant, p=partner)
        rec = s.run(f"MATCH (e:{label} {{name: 'Acme Corp'}})-[:SUPPLIES]->(p) RETURN count(DISTINCT e) AS acme,"
                    " collect(p.name) AS partners").single()
        s.run(f"MATCH (n:{label}) DETACH DELETE n")
    assert rec["acme"] == 1 and sorted(rec["partners"]) == ["Globex", "Initech"], "both tenants share one node"


def test_uniqueness_constraint_covers_tenant_and_name(neo4j_driver: Any) -> None:
    with neo4j_driver.session() as s:
        rows = [r.data() for r in s.run("SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties, type")]
    entity = [r for r in rows if r["name"] == "entity_tenant_name"]
    assert entity and entity[0]["properties"] == ["tenant_id", "canonical_name"]
    assert "UNIQUENESS" in entity[0]["type"]


def test_deleting_a_documents_chunks_removes_facts_only_it_supported(neo4j_driver: Any) -> None:
    t = f"d-{uuid.uuid4().hex[:6]}"
    store = GraphStore(neo4j_driver)
    store.upsert_chunk_facts(t, "doc1", "c1", [EntityIn("Deployment", "resource"), EntityIn("ReplicaSet", "resource")],
                             [RelationIn("Deployment", "MANAGES", "ReplicaSet")])
    store.upsert_chunk_facts(t, "doc2", "c2", [EntityIn("ReplicaSet", "resource"), EntityIn("Pod", "resource")],
                             [RelationIn("ReplicaSet", "MANAGES", "Pod")])
    store.delete_chunks(t, ["c1"])
    stats = store.stats(t)
    assert stats == {"entities": 2, "relations": 1, "chunks": 1}  # Deployment and its edge are gone
