"""Build a bounded, time-consistent context snapshot for one reply."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from veyrasoul.affect.engine import AffectState
from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.memory.retrieval import HybridRetriever, RetrievedMemory
from veyrasoul.runtime.latest_value import LatestValue


@dataclass(frozen=True, slots=True)
class ContextBundle:
    generated_at_ms: int
    visual: VisualSnapshot | None
    memories: tuple[RetrievedMemory, ...]
    recent_turns: tuple[dict[str, object], ...]
    affect: AffectState
    retrieval_timed_out: bool = False


class ContextAssembler:
    def __init__(
        self,
        visual_slot: LatestValue[VisualSnapshot],
        retriever: HybridRetriever,
        *,
        visual_max_age_ms: int = 8_000,
        retrieval_deadline_ms: int = 80,
    ) -> None:
        self.visual_slot = visual_slot
        self.retriever = retriever
        self.visual_max_age_ms = max(100, int(visual_max_age_ms))
        self.retrieval_deadline_ms = max(5, int(retrieval_deadline_ms))

    async def assemble(
        self,
        query: str,
        recent_turns: list[dict[str, object]],
        affect: AffectState,
    ) -> ContextBundle:
        generated_at = int(time.time() * 1000)
        visual_version = await self.visual_slot.snapshot()
        visual = visual_version.value
        if visual is not None and not visual.is_fresh(self.visual_max_age_ms, generated_at):
            visual = None
        timed_out = False
        try:
            memories = await asyncio.wait_for(
                asyncio.to_thread(self.retriever.retrieve, query, 8, generated_at),
                timeout=self.retrieval_deadline_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            memories = []
            timed_out = True
        return ContextBundle(
            generated_at_ms=generated_at,
            visual=visual,
            memories=tuple(memories),
            recent_turns=tuple(recent_turns[-8:]),
            affect=affect,
            retrieval_timed_out=timed_out,
        )
