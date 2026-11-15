from __future__ import annotations

import pytest

from cortex.graph.store import canonical_name, relation_type, search_name
from cortex.retrieval.sparse import or_query
from cortex.router import RuleRouter


@pytest.mark.parametrize(
    ("question", "route"),
    [
        ("What is a Pod?", "content"),
        ("How do I configure a liveness probe?", "content"),
        ("Which object manages ReplicaSets?", "relationship"),
        ("How is a Deployment related to a ReplicaSet and to Pods?", "relationship"),
        ("What depends on the kube-apiserver?", "relationship"),
        ("Explain how a Deployment controls Pods and what fields configure the rollout", "both"),
    ],
)
def test_rule_router(question: str, route: str) -> None:
    assert RuleRouter().route(question) == route


def test_canonical_names_fold_spelling_variants() -> None:
    assert canonical_name("ReplicaSet") == canonical_name("Replica Sets") == canonical_name("replica-set")
    assert canonical_name("Pods") == canonical_name("pod")
    assert canonical_name("the kube-apiserver") == canonical_name("kube-apiserver")
    assert canonical_name("Ingress") == "ingress"  # double-s words keep their s


def test_relation_types_are_safe_identifiers() -> None:
    assert relation_type("manages") == "MANAGES"
    assert relation_type("runs on") == "RUNS_ON"
    assert relation_type("x'}) DETACH DELETE n //") == "X_DETACH_DELETE_N"


def test_search_name_splits_camel_case() -> None:
    assert search_name("ReplicaSet") == "replica set"


def test_or_query_contains_only_safe_terms() -> None:
    q = or_query("What's kube-proxy's role? '); DROP TABLE chunks; --")
    assert q is not None
    assert ";" not in q and "'" not in q and "--" not in q
    assert "(kube <-> proxy)" in q
    assert or_query("?! ...") is None
