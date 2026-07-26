"""Portable embedding provider contract with a deterministic local baseline."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Contract implemented by local ONNX and remote embedding adapters."""

    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...

    def embed_query(self, text: str) -> Sequence[float]: ...


@dataclass(frozen=True, slots=True)
class HashingEmbeddingProvider:
    """Dependency-free semantic-ish fallback; deterministic, not a mock."""

    dimension: int = 384
    model_id: str = "anima-hashing-v1"

    def __post_init__(self) -> None:
        if not 32 <= int(self.dimension) <= 4096:
            raise ValueError("embedding dimension must be between 32 and 4096")

    def embed_documents(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._embed(text)

    def _embed(self, text: str) -> tuple[float, ...]:
        normalized = re.sub(r"\s+", " ", str(text or "").strip()).casefold()
        vector = [0.0] * self.dimension
        tokens = re.findall(r"[\w]+|[\u3400-\u9fff]", normalized)
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "little") % self.dimension
            vector[index] += 1.0 if digest[8] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return tuple(vector)


def validate_embeddings(
    vectors: Sequence[Sequence[float]], expected_count: int, dimension: int
) -> list[tuple[float, ...]]:
    if len(vectors) != expected_count:
        raise ValueError("embedding provider returned the wrong batch size")
    normalized: list[tuple[float, ...]] = []
    for vector in vectors:
        values = tuple(float(value) for value in vector)
        if len(values) != dimension or not all(math.isfinite(value) for value in values):
            raise ValueError("embedding provider returned an invalid vector")
        normalized.append(values)
    return normalized
