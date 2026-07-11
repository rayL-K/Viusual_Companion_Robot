from __future__ import annotations

import asyncio
import time

from veyrasoul.affect.engine import AffectCue
from veyrasoul.domain.perception import VisualSnapshot
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


def test_text_and_visual_evidence_update_affect_with_real_elapsed_decay(tmp_path) -> None:
    async def scenario() -> None:
        now = [100.0]
        store = MemoryStore(tmp_path / "memory.db")
        visual = LatestValue()
        assembler = ContextAssembler(visual, HybridRetriever(store))
        session = SessionKernel("s1", store, assembler, monotonic_clock=lambda: now[0])
        await visual.publish(
            VisualSnapshot(
                frame_id="camera:1",
                observed_at_ms=int(time.time() * 1000),
                sequence=1,
                face_emotions={"happy": 0.9},
            )
        )

        _, first = await session.begin_turn("我很开心，谢谢你")
        assert first.affect.valence > 0.4
        assert first.affect.arousal > 0.3
        assert first.affect.affinity > 0.3
        assert first.affect.trust > 0.25

        await visual.publish(
            VisualSnapshot(
                frame_id="camera:2",
                observed_at_ms=int(time.time() * 1000),
                sequence=2,
            )
        )
        now[0] += 90.0
        _, decayed = await session.begin_turn("今天聊点别的")
        assert 0.0 < decayed.affect.valence < first.affect.valence * 0.2
        assert decayed.affect.affinity > first.affect.affinity * 0.99

    asyncio.run(scenario())
