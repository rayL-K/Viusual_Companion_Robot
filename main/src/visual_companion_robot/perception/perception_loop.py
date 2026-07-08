"""感知主循环 — 摄像头采集 + 场景分析（双后端）。

负责：
1. 从摄像头读取帧
2. 调用 SceneAnalyzer 生成 PerceptionFrame
3. 通过 RuntimeBus 广播 vision 事件
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import cv2

from .scene_analyzer import SceneAnalyzer
from .vision import PerceptionFrame, now_iso

logger = logging.getLogger(__name__)


class PerceptionLoop:
    """摄像头 → 场景分析 → RuntimeBus 的主循环。

    Args:
        analyzer: 已初始化好的 SceneAnalyzer 实例。
        bus_emit: 事件广播回调函数，签名为 (event_type: str, payload: dict) -> None。
        camera_id: OpenCV 摄像头索引，默认 0。
        analyze_interval_sec: 场景分析间隔秒数。
        frame_width: 采集分辨率宽度，默认 640。
        frame_height: 采集分辨率高度，默认 480。
    """

    def __init__(
        self,
        analyzer: SceneAnalyzer,
        bus_emit=None,
        camera_id: int = 0,
        analyze_interval_sec: float = 2.0,
        frame_width: int = 640,
        frame_height: int = 480,
    ) -> None:
        self._analyzer = analyzer
        self._emit = bus_emit or (lambda e, p: None)
        self._camera_id = camera_id
        self._interval = analyze_interval_sec
        self._width = frame_width
        self._height = frame_height
        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._last_analyze_at = 0.0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动感知循环。"""

        self._cap = cv2.VideoCapture(self._camera_id)
        if not self._cap.isOpened():
            import sys
            if sys.platform == "win32":
                self._cap = cv2.VideoCapture(self._camera_id, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            logger.error("无法打开摄像头 #%d", self._camera_id)
            self._emit("error", {"message": f"无法打开摄像头 #{self._camera_id}"})
            return

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._running = True
        logger.info(
            "感知循环已启动 (摄像头 #%d, %dx%d, 间隔 %.1fs, 后端=%s)",
            self._camera_id, self._width, self._height, self._interval,
            "local" if hasattr(self._analyzer, "_backend") and self._analyzer._backend == "local" else "cloud",
        )

        asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("感知循环已停止")

    # ------------------------------------------------------------------
    # 内部循环
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """主循环：抓帧 → 分析 → 广播。"""

        loop = asyncio.get_event_loop()
        frame = PerceptionFrame()

        while self._running and self._cap and self._cap.isOpened():
            ret, bgr = await loop.run_in_executor(None, self._cap.read)
            if not ret:
                await asyncio.sleep(0.1)
                continue

            frame.frame_width = self._width
            frame.frame_height = self._height

            now = time.perf_counter()
            if now - self._last_analyze_at >= self._interval:
                try:
                    frame = await loop.run_in_executor(None, self._analyzer.analyze, bgr, frame)
                    self._last_analyze_at = now
                    self._emit("vision.frame", frame.to_dict())
                except Exception:
                    logger.exception("场景分析失败")

            await asyncio.sleep(0.1)
