"""End-to-end long-term memory pipeline used by orchestration adapters."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

from .curator import CuratedFact, FactCandidate, MemoryCurator
from .namespace import MemoryNamespace, assert_bound_store
from .prompt_boundary import RagPromptContext, build_rag_prompt_context
from .retrieval import HybridRetriever
from .store import MemoryStore


class FactExtractor(Protocol):
    def extract(
        self, *, namespace: MemoryNamespace, user_text: str, assistant_text: str
    ) -> Sequence[FactCandidate]: ...


@dataclass(frozen=True, slots=True)
class CuratedTurn:
    turn_row_id: int
    episode_entry_id: int
    facts: tuple[CuratedFact, ...]


class ExplicitPreferenceExtractor:
    """Conservative baseline: only persist direct first-person preferences."""

    _PATTERNS = (
        re.compile(r"(?:我喜欢|我偏好)(?P<value>[^。！？!?]{1,80})"),
        re.compile(r"请(?:叫我|称呼我)(?P<value>[^。！？!?]{1,40})"),
    )

    def extract(
        self, *, namespace: MemoryNamespace, user_text: str, assistant_text: str
    ) -> list[FactCandidate]:
        del assistant_text
        candidates: list[FactCandidate] = []
        for index, pattern in enumerate(self._PATTERNS):
            for match in pattern.finditer(user_text):
                candidates.append(
                    FactCandidate(
                        subject="用户",
                        predicate="偏好" if index == 0 else "希望的称呼",
                        value=match.group("value"),
                        confidence=0.95,
                        source=f"conversation:{namespace.key}",
                        evidence_kind="explicit",
                    )
                )
        return candidates


class MemoryPipeline:
    def __init__(
        self,
        store: MemoryStore,
        namespace: MemoryNamespace,
        *,
        extractor: FactExtractor | None = None,
        retriever: HybridRetriever | None = None,
    ) -> None:
        assert_bound_store(store, namespace)
        self.store = store
        self.namespace = namespace
        self.extractor = extractor or ExplicitPreferenceExtractor()
        self.curator = MemoryCurator(store)
        self.retriever = retriever or HybridRetriever(store)
        with self.store.connection() as connection:
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_turn_episode
                ON memory_entries(source)
                WHERE kind='episode' AND active=1 AND source LIKE 'turn:%'
                """
            )

    def process_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_text: str,
        assistant_text: str,
    ) -> CuratedTurn:
        row_id = self.store.add_turn(session_id, turn_id, user_text, assistant_text)
        episode_id, created = self._add_episode_once(
            session_id=session_id,
            turn_id=turn_id,
            user_text=user_text,
            assistant_text=assistant_text,
        )
        if not created:
            return CuratedTurn(row_id, episode_id, ())
        candidates = self.extractor.extract(
            namespace=self.namespace,
            user_text=user_text,
            assistant_text=assistant_text,
        )
        return CuratedTurn(
            row_id,
            episode_id,
            tuple(self.curator.curate_many(candidates)),
        )

    def context_for(self, query: str, *, limit: int = 8, max_chars: int = 8_000) -> RagPromptContext:
        return build_rag_prompt_context(
            self.retriever.retrieve(query, limit=limit), max_chars=max_chars
        )

    def _add_episode_once(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_text: str,
        assistant_text: str,
    ) -> tuple[int, bool]:
        digest = hashlib.sha256(
            f"{self.namespace.key}\0{session_id}\0{turn_id}".encode("utf-8")
        ).hexdigest()
        source = f"turn:{digest}"
        with self.store.connection(immediate=True) as connection:
            existing = connection.execute(
                """
                SELECT id, body FROM memory_entries
                WHERE kind='episode' AND source=? AND active=1
                """,
                (source,),
            ).fetchone()
            body = f"用户：{user_text}\nAnima：{assistant_text}"
            if existing is not None:
                if str(existing["body"]) != body:
                    raise ValueError("turn episode already exists with different content")
                return int(existing["id"]), False
            entry_id = self.store._insert_entry(
                connection,
                kind="episode",
                title=f"对话 {turn_id}"[:240],
                body=body,
                source=source,
                importance=0.5,
                observed_at_ms=int(time.time() * 1000),
                embedding=None,
                metadata={
                    "namespace": self.namespace.key,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "trusted": False,
                    "instructions_allowed": False,
                },
            )
            return entry_id, True
