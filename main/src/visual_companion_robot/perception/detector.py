"""YOLO 目标检测器 — 封装 model_runtime 的 RknnEngine。

提供简单的检测接口：输入一帧 → 输出检测结果。
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from visual_companion_robot.integrations.model_runtime import (
    DetectionResult,
    ModelNotLoadedError,
    ModelRuntimeError,
    RknnEngine,
)

logger = logging.getLogger(__name__)


class YoloDetector:
    """YOLO 目标检测器。

    Args:
        model_path: RKNN 模型文件路径。
        conf_threshold: 置信度阈值。
        npu_target: NPU 平台（rk3588）。
        cpu_fallback: 无 NPU 时是否降级到 ONNX CPU。
    """

    def __init__(
        self,
        model_path: str,
        conf_threshold: float = 0.5,
        npu_target: str = "rk3588",
        cpu_fallback: bool = True,
    ) -> None:
        self._conf_threshold = conf_threshold
        self._engine = RknnEngine(target_platform=npu_target, cpu_fallback=cpu_fallback)
        self._model_path = model_path
        self._loaded = False

    def load(self) -> None:
        """加载模型。可重复调用（幂等）。"""

        if self._loaded:
            return
        self._engine.load(self._model_path)
        self._loaded = True
        logger.info("YOLO 检测器已加载")

    def is_loaded(self) -> bool:
        return self._loaded and self._engine.is_loaded()

    def unload(self) -> None:
        self._engine.unload()
        self._loaded = False

    def detect(self, image: np.ndarray) -> DetectionResult:
        """对 BGR 帧执行检测。

        Args:
            image: BGR 图像 (H, W, 3)。

        Returns:
            DetectionResult — 空列表表示未检测到目标。
        """
        if not self._loaded:
            raise ModelNotLoadedError("YOLO 检测器未加载，请先调用 load()")

        return self._engine.detect(image, conf_threshold=self._conf_threshold)

    def detect_for_scene(self, image: np.ndarray) -> str:
        """检测并返回可读的场景摘要文字。

        Args:
            image: BGR 图像。

        Returns:
            中文场景描述，如"画面中有 1 个人，1 部手机"。
        """
        return self.describe(self.detect(image))

    @staticmethod
    def describe(result: DetectionResult) -> str:
        """把一次检测结果转成简短场景描述，避免重复推理。"""

        if not result.detections:
            return "画面中未检测到明显物体"

        counts: dict[str, int] = {}
        for det in result.detections:
            counts[det.class_name] = counts.get(det.class_name, 0) + 1

        parts = []
        for name, count in sorted(counts.items(), key=lambda x: -x[1]):
            if count == 1:
                parts.append(f"1 个{name}")
            else:
                parts.append(f"{count} 个{name}")

        return "画面中有" + "，".join(parts)
