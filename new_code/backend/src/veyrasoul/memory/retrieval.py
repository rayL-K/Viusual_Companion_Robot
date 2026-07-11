"""Hybrid lexical/vector retrieval with time and importance fusion."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from .store import MemoryEntry, MemoryStore


EmbeddingFunction = Callable[[str], Sequence[float]]


@dataclass(frozen=True, slots=True)
class RetrievedMemory:
    entry: MemoryEntry
    score: float
    lexical_rank: int | None
    vector_rank: int | None


class HybridRetriever:
    def __init__(
        self,
        store: MemoryStore,
        embed: EmbeddingFunction | None = None,
        *,
        rrf_constant: int = 60,
        recency_half_life_days: float = 30.0,
    ) -> None:
        self.store = store
        self.embed = embed
        self.rrf_constant = max(1, int(rrf_constant))
        self.recency_half_life_ms = max(1.0, recency_half_life_days) * 86_400_000

    def retrieve(self, query: str, limit: int = 8, now_ms: int | None = None) -> list[RetrievedMemory]:
        normalized = str(query or "").strip()
        if not normalized:
            return []
        pool_size = max(20, min(200, int(limit) * 6))
        lexical = self.store.search_lexical(normalized, pool_size)
        lexical_ranks = {entry.id: rank for rank, (entry, _) in enumerate(lexical, start=1)}
        entries = {entry.id: entry for entry, _ in lexical}

        vector_scores: list[tuple[int, float]] = []
        if self.embed is not None:
            query_embedding = tuple(float(value) for value in self.embed(normalized))
            for entry in self.store.entries_with_embeddings():
                if len(entry.embedding) != len(query_embedding) or not query_embedding:
                    continue
                vector_scores.append((entry.id, _cosine(query_embedding, entry.embedding)))
                entries[entry.id] = entry
            vector_scores.sort(key=lambda item: item[1], reverse=True)
            vector_scores = vector_scores[:pool_size]
        vector_ranks = {entry_id: rank for rank, (entry_id, _) in enumerate(vector_scores, start=1)}

        reference = int(time.time() * 1000) if now_ms is None else int(now_ms)
        results: list[RetrievedMemory] = []
        for entry_id in lexical_ranks.keys() | vector_ranks.keys():
            entry = entries[entry_id]
            lexical_rank = lexical_ranks.get(entry_id)
            vector_rank = vector_ranks.get(entry_id)
            score = 0.0
            if lexical_rank is not None:
                score += 1.0 / (self.rrf_constant + lexical_rank)
            if vector_rank is not None:
                score += 1.0 / (self.rrf_constant + vector_rank)
            age = max(0, reference - entry.observed_at_ms)
            freshness = math.exp(-math.log(2) * age / self.recency_half_life_ms)
            score += entry.importance * 0.008 + freshness * 0.004
            results.append(RetrievedMemory(entry, score, lexical_rank, vector_rank))
        results.sort(key=lambda item: (item.score, item.entry.observed_at_ms), reverse=True)
        return results[: max(1, min(int(limit), 30))]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)
