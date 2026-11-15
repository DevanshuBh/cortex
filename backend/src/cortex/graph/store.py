"""Neo4j entity graph with property-based tenancy (one database; Community Edition).

Every node and relationship carries ``tenant_id``; every MERGE keys on it. Merging on the entity name alone would
turn two tenants' "Acme Corp" into one shared node and leak every relationship attached to it (guide step 3.1).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from neo4j import Driver, GraphDatabase

from cortex.config import get_settings

SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT entity_tenant_name IF NOT EXISTS FOR (e:Entity) REQUIRE (e.tenant_id, e.canonical_name)"
    " IS UNIQUE",
    "CREATE CONSTRAINT chunk_tenant_id IF NOT EXISTS FOR (c:Chunk) REQUIRE (c.tenant_id, c.chunk_id) IS UNIQUE",
    "CREATE INDEX entity_tenant IF NOT EXISTS FOR (e:Entity) ON (e.tenant_id)",
    "CREATE INDEX chunk_document IF NOT EXISTS FOR (c:Chunk) ON (c.tenant_id, c.document_id)",
    "CREATE FULLTEXT INDEX entity_names IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.search_name]",
]

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_REL_TYPE = re.compile(r"[^A-Z0-9_]+")


def canonical_name(name: str) -> str:
    """Deterministic key: case, spacing and punctuation folded, simple plural stripped.

    "Replica Sets", "replica-set" and "ReplicaSet" share one key. The display name is stored separately.
    """
    key = _NON_ALNUM.sub("", name.lower().strip())
    for article in ("the", "an", "a"):
        if name.lower().startswith(article + " ") and len(key) > len(article) + 2:
            key = key[len(article) :]
            break
    if len(key) > 3 and key.endswith("s") and not key.endswith("ss"):
        key = key[:-1]
    return key[:120]


def relation_type(rel: str) -> str:
    t = _REL_TYPE.sub("_", rel.strip().upper().replace(" ", "_").replace("-", "_"))
    t = re.sub(r"_+", "_", t).strip("_")
    return (t or "RELATED_TO")[:40]


def search_name(name: str) -> str:
    """Spaced form for the full-text index: "ReplicaSet" → "replica set" so either spelling matches."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return _NON_ALNUM.sub(" ", spaced.lower()).strip()


@dataclass(frozen=True, slots=True)
class EntityIn:
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class RelationIn:
    source: str
    relation: str
    target: str


@lru_cache
def get_driver() -> Driver:
    s = get_settings()
    return GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password.get_secret_value()))


class GraphStore:
    def __init__(self, driver: Driver | None = None) -> None:
        self._driver = driver or get_driver()

    def ensure_schema(self) -> None:
        with self._driver.session() as s:
            for stmt in SCHEMA_STATEMENTS:
                s.run(stmt)

    def upsert_chunk_facts(
        self,
        tenant_id: str,
        document_id: str,
        chunk_id: str,
        entities: Sequence[EntityIn],
        relations: Sequence[RelationIn],
    ) -> None:
        """Idempotent: replaying the same chunk adds nothing new."""
        ents: dict[str, dict[str, str]] = {}
        for e in entities:
            key = canonical_name(e.name)
            if key:
                ents.setdefault(
                    key,
                    {
                        "key": key,
                        "name": e.name.strip()[:120],
                        "type": e.type[:40],
                        "search": search_name(e.name),
                    },
                )
        rels = []
        for r in relations:
            src, dst = canonical_name(r.source), canonical_name(r.target)
            if src and dst and src != dst and src in ents and dst in ents:
                rels.append({"src": src, "dst": dst, "type": relation_type(r.relation)})
        with self._driver.session() as s:
            s.execute_write(self._write_chunk, tenant_id, document_id, chunk_id, list(ents.values()), rels)

    @staticmethod
    def _write_chunk(
        tx: Any, t: str, doc: str, cid: str, ents: list[dict[str, str]], rels: list[dict[str, str]]
    ) -> None:
        tx.run(
            "MERGE (c:Chunk {tenant_id: $t, chunk_id: $cid}) SET c.document_id = $doc "
            "WITH c UNWIND $ents AS ent "
            "MERGE (e:Entity {tenant_id: $t, canonical_name: ent.key}) "
            "  ON CREATE SET e.name = ent.name, e.type = ent.type, e.search_name = ent.search "
            "MERGE (e)-[:MENTIONED_IN {tenant_id: $t}]->(c)",
            t=t,
            cid=cid,
            doc=doc,
            ents=ents,
        )
        tx.run(
            "UNWIND $rels AS r "
            "MATCH (a:Entity {tenant_id: $t, canonical_name: r.src}) "
            "MATCH (b:Entity {tenant_id: $t, canonical_name: r.dst}) "
            "MERGE (a)-[rel:REL {tenant_id: $t, type: r.type}]->(b) "
            "  ON CREATE SET rel.chunk_ids = [$cid] "
            "  ON MATCH SET rel.chunk_ids = CASE WHEN $cid IN rel.chunk_ids THEN rel.chunk_ids "
            "                                    ELSE rel.chunk_ids + $cid END",
            t=t,
            cid=cid,
            rels=rels,
        )

    def chunk_ids_for_document(self, tenant_id: str, document_id: str) -> set[str]:
        with self._driver.session() as s:
            res = s.run(
                "MATCH (c:Chunk {tenant_id: $t, document_id: $d}) RETURN c.chunk_id AS id",
                t=tenant_id,
                d=document_id,
            )
            return {r["id"] for r in res}

    def delete_chunks(self, tenant_id: str, chunk_ids: Sequence[str]) -> None:
        """Remove facts supported only by these chunks; entities left with no support are deleted too."""
        if not chunk_ids:
            return
        ids = list(chunk_ids)
        with self._driver.session() as s:
            s.execute_write(self._delete, tenant_id, ids)

    @staticmethod
    def _delete(tx: Any, t: str, ids: list[str]) -> None:
        tx.run(
            "MATCH (:Entity {tenant_id: $t})-[r:REL {tenant_id: $t}]->(:Entity {tenant_id: $t}) "
            "WHERE any(c IN r.chunk_ids WHERE c IN $ids) "
            "SET r.chunk_ids = [c IN r.chunk_ids WHERE NOT c IN $ids] "
            "WITH r WHERE size(r.chunk_ids) = 0 DELETE r",
            t=t,
            ids=ids,
        )
        tx.run("MATCH (c:Chunk {tenant_id: $t}) WHERE c.chunk_id IN $ids DETACH DELETE c", t=t, ids=ids)
        tx.run(
            "MATCH (e:Entity {tenant_id: $t}) WHERE NOT (e)-[:MENTIONED_IN]->() AND NOT (e)-[:REL]-() DELETE e",
            t=t,
        )

    def stats(self, tenant_id: str) -> dict[str, int]:
        with self._driver.session() as s:
            rec = s.run(
                "CALL () { MATCH (e:Entity {tenant_id: $t}) RETURN count(e) AS entities } "
                "CALL () { MATCH (:Entity {tenant_id: $t})-[r:REL {tenant_id: $t}]->() RETURN count(r) AS rels } "
                "CALL () { MATCH (c:Chunk {tenant_id: $t}) RETURN count(c) AS chunks } "
                "RETURN entities, rels, chunks",
                t=tenant_id,
            ).single()
            return (
                {"entities": rec["entities"], "relations": rec["rels"], "chunks": rec["chunks"]}
                if rec
                else {}
            )
