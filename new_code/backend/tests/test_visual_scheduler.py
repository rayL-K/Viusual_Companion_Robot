import asyncio

import pytest

from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.perception import VisualFrame, VisualSemanticScheduler


def jpeg(label: bytes) -> bytes:
    return b"\xff\xd8" + label + b"\xff\xd9"


class FakeAnalyzer:
    def __init__(self) -> None:
        self.frames: list[VisualFrame] = []

    async def analyze(self, frame: VisualFrame) -> VisualSnapshot:
        self.frames.append(frame)
        return VisualSnapshot(
            frame_id=str(frame.sequence),
            observed_at_ms=frame.observed_at_ms,
            sequence=frame.sequence,
            semantic_caption=f"scene-{frame.sequence}",
        )


def test_visual_scheduler_keeps_latest_frame_during_budget_window() -> None:
    async def scenario() -> None:
        analyzer = FakeAnalyzer()
        snapshots: list[VisualSnapshot] = []
        scheduler = VisualSemanticScheduler(analyzer, refresh_seconds=0.04)
        await scheduler.start(lambda snapshot: _append(snapshots, snapshot))
        scheduler.submit_jpeg(jpeg(b"first"), 1, 1000)
        await asyncio.sleep(0.01)
        scheduler.submit_jpeg(jpeg(b"old"), 2, 2000)
        scheduler.submit_jpeg(jpeg(b"latest"), 3, 3000)
        for _ in range(100):
            if len(analyzer.frames) == 2:
                break
            await asyncio.sleep(0.01)
        await scheduler.close()

        assert [frame.sequence for frame in analyzer.frames] == [1, 3]
        assert [snapshot.semantic_caption for snapshot in snapshots] == ["scene-1", "scene-3"]

    asyncio.run(scenario())


def test_visual_scheduler_rejects_invalid_jpeg() -> None:
    scheduler = VisualSemanticScheduler(FakeAnalyzer())
    with pytest.raises(ValueError, match="JPEG"):
        scheduler.submit_jpeg(b"not-an-image", 1, 1000)


async def _append(values: list[VisualSnapshot], value: VisualSnapshot) -> None:
    values.append(value)
