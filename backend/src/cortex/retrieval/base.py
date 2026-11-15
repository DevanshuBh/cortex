"""Retriever interface shared by dense, sparse, graph and fused retrieval (Strategy pattern)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class Candidate:
    chunk_id: str
    score: float
    source: str  # "dense" | "sparse" | "graph" | "rrf" | "rerank"
    text: str = ""
    heading_path: str = ""
    document_id: str = ""
    ranks: dict[str, int] = field(default_factory=dict)


class Retriever(Protocol):
    @property
    def name(self) -> str: ...

    def search(self, tenant_id: str, query: str, k: int) -> list[Candidate]: ...
