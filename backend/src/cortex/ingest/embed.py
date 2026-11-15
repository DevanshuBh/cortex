"""Pinned embedding model and cross-encoder reranker (docs/adr/0003).

Vectors from two different models must never share an index; the model name and revision are fixed in config
and a model change is a re-embedding migration (staff step S.6).
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from cortex.config import get_settings

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder, SentenceTransformer


class Embedder:
    def __init__(self, model: SentenceTransformer, query_prefix: str, max_tokens: int) -> None:
        self._model = model
        self._prefix = query_prefix
        self._max_tokens = max_tokens
        self._lock = threading.Lock()
        self.dim = int(model.get_sentence_embedding_dimension() or 0)

    def count_tokens(self, text: str) -> int:
        """Tokens as the model sees them, including the [CLS]/[SEP] specials."""
        return len(self._model.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])

    def embed_passages(self, texts: Sequence[str], batch_size: int = 32) -> np.ndarray:
        with self._lock:
            vecs = self._model.encode(
                list(texts),
                batch_size=batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return np.asarray(vecs, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        vec: np.ndarray = self.embed_passages([self._prefix + text])[0]
        return vec


class Reranker:
    def __init__(self, model: CrossEncoder) -> None:
        self._model = model
        self._lock = threading.Lock()

    def scores(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        with self._lock:
            out = self._model.predict([(query, p) for p in passages], batch_size=32, show_progress_bar=False)
        return [float(x) for x in np.asarray(out).reshape(-1)]


@lru_cache
def get_embedder() -> Embedder:
    from sentence_transformers import SentenceTransformer

    s = get_settings()
    model = SentenceTransformer(s.embedding_model, revision=s.embedding_revision, device=s.models_device)
    model.max_seq_length = s.embedding_max_tokens
    emb = Embedder(model, s.embedding_query_prefix, s.embedding_max_tokens)
    if emb.dim != s.embedding_dim:
        raise RuntimeError(f"embedding model produces {emb.dim} dims, schema expects {s.embedding_dim}")
    return emb


@lru_cache
def get_reranker() -> Reranker:
    from sentence_transformers import CrossEncoder

    s = get_settings()
    return Reranker(CrossEncoder(s.reranker_model, revision=s.reranker_revision, device=s.models_device))
