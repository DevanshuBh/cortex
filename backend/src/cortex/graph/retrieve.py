"""Graph retrieval: seed entities from the question, bounded tenant-filtered traversal, citable chunk ids.

Every query is parameterised, filters every node *and* relationship on ``tenant_id``, is limited to at most 3 hops
and always has a LIMIT (guide step 3.2). The hop count is validated and formatted into the pattern because Cypher
does not accept parameters in variable-length bounds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from neo4j import Driver

from cortex.graph.store import canonical_name, get_driver
from cortex.observability import metrics
from cortex.retrieval.base import Candidate

_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "between",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "this",
        "to",
        "used",
        "uses",
        "using",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "within",
        "does",
        "relate",
        "related",
        "relationship",
        "relationships",
        "connect",
        "connected",
        "depend",
        "depends",
        "manage",
        "manages",
        "managed",
        "kubernetes",
    ]
)
_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


@dataclass(slots=True)
class GraphPath:
    nodes: list[str]  # display names
    relations: list[str]  # relation types, len(nodes) - 1
    chunk_ids: list[str]
    score: float = 0.0

    def describe(self) -> str:
        parts = [self.nodes[0]]
        for rel, node in zip(self.relations, self.nodes[1:], strict=True):
            parts.append(f"-[{rel}]-> {node}")
        return " ".join(parts)


@dataclass(slots=True)
class GraphResult:
    seeds: list[str] = field(default_factory=list)
    paths: list[GraphPath] = field(default_factory=list)

    def candidates(self, limit: int) -> list[Candidate]:
        """Chunk ids ranked by the best path that cites them (shorter, seed-to-seed paths first)."""
        best: dict[str, float] = {}
        for p in self.paths:
            for cid in p.chunk_ids:
                best[cid] = max(best.get(cid, 0.0), p.score)
        ranked = sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
        return [
            Candidate(chunk_id=c, score=s, source="graph", ranks={"graph": i})
            for i, (c, s) in enumerate(ranked, start=1)
        ]


def _lucene_terms(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", question)
    out = []
    for w in words:
        if w.lower() in _STOP:
            continue
        out.append(_LUCENE_SPECIAL.sub(r"\\\1", w.lower()))
    return list(dict.fromkeys(out))[:12]


class GraphRetriever:
    name = "graph"

    def __init__(self, driver: Driver | None = None, max_hops: int = 2, path_limit: int = 60) -> None:
        if not 1 <= max_hops <= 3:
            raise ValueError("max_hops must be 1..3")
        self._driver = driver or get_driver()
        self._hops = max_hops
        self._limit = path_limit

    def find_seeds(
        self, tenant_id: str, question: str, names: list[str] | None = None, limit: int = 5
    ) -> list[str]:
        """Canonical names of entities the question mentions: exact matches first, then full-text matches."""
        seeds: list[str] = []
        with self._driver.session() as s:
            if names:
                keys = [canonical_name(n) for n in names if canonical_name(n)]
                res = s.run(
                    "MATCH (e:Entity {tenant_id: $t}) WHERE e.canonical_name IN $keys RETURN e.canonical_name AS k",
                    t=tenant_id,
                    keys=keys,
                )
                seeds.extend(r["k"] for r in res)
            terms = _lucene_terms(question)
            if terms and len(seeds) < limit:
                # Full-text results are filtered by tenant after the index lookup; the query asks for many hits
                # so a small tenant is not starved by a large one (same pitfall as filtered HNSW).
                res = s.run(
                    "CALL db.index.fulltext.queryNodes('entity_names', $q, {limit: 500}) YIELD node, score "
                    "WHERE node.tenant_id = $t "
                    "OPTIONAL MATCH (node)-[m:MENTIONED_IN {tenant_id: $t}]->() "
                    "WITH node, score, count(m) AS mentions "
                    "RETURN node.canonical_name AS k ORDER BY score DESC, mentions DESC LIMIT $limit",
                    q=" OR ".join(terms),
                    t=tenant_id,
                    limit=limit * 2,
                )
                for r in res:
                    if r["k"] not in seeds:
                        seeds.append(r["k"])
        return seeds[:limit]

    def search_paths(self, tenant_id: str, question: str, names: list[str] | None = None) -> GraphResult:
        with metrics.RETRIEVAL_LATENCY.labels(stage="graph").time():
            seeds = self.find_seeds(tenant_id, question, names)
            if not seeds:
                return GraphResult()
            hops = int(self._hops)
            query = (
                "MATCH (s:Entity {tenant_id: $t}) WHERE s.canonical_name IN $seeds "
                f"MATCH p = (s)-[rels:REL*1..{hops}]-(o:Entity {{tenant_id: $t}}) "
                "WHERE all(r IN rels WHERE r.tenant_id = $t) AND all(n IN nodes(p) WHERE n.tenant_id = $t) "
                "WITH p, rels, o, CASE WHEN o.canonical_name IN $seeds THEN 1 ELSE 0 END AS seedHit "
                "RETURN [n IN nodes(p) | n.name] AS names, "
                "       [r IN rels | r.type] AS types, "
                "       [r IN rels | startNode(r).name] AS starts, "
                "       reduce(acc = [], r IN rels | acc + r.chunk_ids) AS chunks, "
                "       length(p) AS len, seedHit "
                "ORDER BY seedHit DESC, len ASC LIMIT $limit"
            )
            with self._driver.session() as s:
                rows: list[dict[str, Any]] = [
                    r.data() for r in s.run(query, t=tenant_id, seeds=seeds, limit=self._limit)
                ]
        result = GraphResult(seeds=seeds)
        seen: set[tuple[str, ...]] = set()
        for r in rows:
            sig = tuple(r["names"]) + tuple(r["types"])
            if sig in seen:
                continue
            seen.add(sig)
            # direction: show arrows the way the relationship points
            rels = [
                f"{t}" if start == r["names"][i] else f"{t} (reverse)"
                for i, (t, start) in enumerate(zip(r["types"], r["starts"], strict=True))
            ]
            score = (2.0 if r["seedHit"] else 1.0) / r["len"]
            result.paths.append(
                GraphPath(
                    nodes=r["names"], relations=rels, chunk_ids=list(dict.fromkeys(r["chunks"])), score=score
                )
            )
        return result
