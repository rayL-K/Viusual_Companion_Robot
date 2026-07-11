"""将高频摄像头关键帧合并为最新值，并按固定预算触发语义视觉。"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from veyrasoul.domain.perception import VisualSnapshot


MAX_JPEG_BYTES = 1536 * 1024


@dataclass(frozen=True, slots=True)
class VisualFrame:
    sequence: int
    observed_at_ms: int
    jpeg: bytes


class VisionAnalyzer(Protocol):
    async def analyze(self, frame: VisualFrame) -> VisualSnapshot: ...


SnapshotSink = Callable[[VisualSnapshot], Awaitable[None]]
ErrorSink = Callable[[Exception], Awaitable[None]]


class VisualSemanticScheduler:
    """单会话最新值调度器；永不让摄像头上传队列无限增长。"""

    def __init__(self, analyzer: VisionAnalyzer, *, refresh_seconds: float = 5.0) -> None:
        self.analyzer = analyzer
        self.refresh_seconds = max(0.05, float(refresh_seconds))
        self._frames: asyncio.Queue[VisualFrame] = asyncio.Queue(maxsize=1)
        self._task: asyncio.Task[None] | None = None
        self._sink: SnapshotSink | None = None
        self._error_sink: ErrorSink | None = None
        self._closed = False

    async def start(self, sink: SnapshotSink, error_sink: ErrorSink | None = None) -> None:
        if self._task is not None:
            raise RuntimeError("视觉语义调度器已经启动")
        if self._closed:
            raise RuntimeError("视觉语义调度器已经关闭")
        self._sink = sink
        self._error_sink = error_sink
        self._task = asyncio.create_task(self._run(), name="visual-semantic-scheduler")

    def submit_jpeg(self, jpeg: bytes, sequence: int, observed_at_ms: int) -> None:
        if self._closed:
            raise RuntimeError("视觉语义调度器已经关闭")
        frame = VisualFrame(
            sequence=max(0, int(sequence)),
            observed_at_ms=max(0, int(observed_at_ms)),
            jpeg=_validate_jpeg(jpeg),
        )
        if self._frames.full():
            self._frames.get_nowait()
        self._frames.put_nowait(frame)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        last_started_at = float("-inf")
        while True:
            frame = await self._frames.get()
            frame = await self._latest_frame_until_budget(frame, last_started_at)
            last_started_at = time.monotonic()
            try:
                snapshot = await self.analyzer.analyze(frame)
                if self._sink is not None:
                    await self._sink(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._error_sink is not None:
                    await self._error_sink(exc)

    async def _latest_frame_until_budget(
        self,
        frame: VisualFrame,
        last_started_at: float,
    ) -> VisualFrame:
        # 等待预算窗口时持续替换为最新帧，避免分析五秒前的排队画面。
        while True:
            remaining = self.refresh_seconds - (time.monotonic() - last_started_at)
            if remaining <= 0:
                return frame
            try:
                newer = await asyncio.wait_for(self._frames.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return frame
            frame = newer


def _validate_jpeg(value: bytes) -> bytes:
    jpeg = bytes(value)
    if not jpeg or len(jpeg) > MAX_JPEG_BYTES:
        raise ValueError("JPEG 为空或超过 1.5 MiB")
    if len(jpeg) < 4 or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise ValueError("视觉帧必须是完整 JPEG")
    return jpeg
