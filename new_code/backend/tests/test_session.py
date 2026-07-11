from __future__ import annotations

import asyncio

from veyrasoul.affect.engine import AffectCue
from veyrasoul.memory.retrieval import HybridRetriever
from veyrasoul.memory.store import MemoryStore
from veyrasoul.orchestration.context import ContextAssembler
from veyrasoul.orchestration.session import SessionKernel
from veyrasoul.runtime.latest_value import LatestValue


def test_cancelled_generation_cannot_commit_memory(tmp_path) -> None:
    async def scenario() -> None:
        store = MemoryStore(tmp_path / "memory.db")
        visual = LatestValue()
        assembler = ContextAssembler(visual, HybridRetriever(store))
        session = SessionKernel("s1", store, assembler)
        generation, _ = await session.begin_turn("你好")
        await session.cancel_current_turn()
        committed = await session.complete_turn(
            generation, "t1", "你好", "你好呀", AffectCue(valence=0.4)
        )
        assert committed is False
        assert store.recent_turns("s1") == []

    asyncio.run(scenario())
