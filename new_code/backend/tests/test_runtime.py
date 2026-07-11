from __future__ import annotations

import asyncio
import time

from veyrasoul.affect.engine import AffectCue, AffectEngine
from veyrasoul.affect.evidence import infer_affect_cue
from veyrasoul.avatar.director import AvatarDirector
from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.runtime.latest_value import LatestValue


def test_latest_value_drops_intermediate_backlog() -> None:
    async def scenario() -> None:
        slot: LatestValue[int] = LatestValue()
        await slot.publish(1)
        await slot.publish(2)
        await slot.publish(3)
        snapshot = await slot.snapshot()
        assert snapshot.version == 3
        assert snapshot.value == 3

    asyncio.run(scenario())


def test_visual_snapshot_freshness_and_summary() -> None:
    now = int(time.time() * 1000)
    snapshot = VisualSnapshot(
        frame_id="f1",
        observed_at_ms=now - 400,
        sequence=3,
        semantic_caption="青年男性戴眼镜，神情专注",
        scene_caption="室内书桌前",
        objects=("耳机", "麦克风"),
    )
    assert snapshot.is_fresh(500, now)
    assert "戴眼镜" in snapshot.prompt_summary()
    assert "耳机" in snapshot.prompt_summary()


def test_affect_drives_continuous_avatar_intent() -> None:
    engine = AffectEngine()
    state = engine.advance(0.0, AffectCue(valence=0.7, arousal=0.65, affinity=0.2))
    intent = AvatarDirector().intent_for(state, phase="speaking")
    assert intent.smile > 0.7
    assert intent.speech_rate > 1.0
    listening = AvatarDirector().intent_for(state, phase="listening")
    assert listening.motion == "listen"


def test_emotion_question_is_not_misread_as_user_emotion() -> None:
    assert infer_affect_cue("你开心吗？") is None
    assert infer_affect_cue("你伤心吗？") is None
