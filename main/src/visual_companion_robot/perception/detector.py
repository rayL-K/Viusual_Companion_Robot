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
    """

    def __init__(
        self,
        model_path: str,
        conf_threshold: float = 0.5,
    ) -> None:
        self._conf_threshold = conf_threshold
        self._engine = RknnEngine()
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
            translated, measure = _COCO_ZH.get(name, (name, "个"))
            parts.append(f"{count}{measure}{translated}")

        return "画面中有" + "、".join(parts)


_COCO_ZH = {
    "person": ("人", ""),
    "bicycle": ("自行车", "辆"),
    "car": ("汽车", "辆"),
    "motorcycle": ("摩托车", "辆"),
    "bus": ("公交车", "辆"),
    "train": ("火车", "列"),
    "truck": ("卡车", "辆"),
    "bird": ("鸟", "只"),
    "cat": ("猫", "只"),
    "dog": ("狗", "只"),
    "backpack": ("背包", "个"),
    "handbag": ("手提包", "个"),
    "bottle": ("瓶子", "个"),
    "wine glass": ("酒杯", "个"),
    "cup": ("杯子", "个"),
    "fork": ("叉子", "把"),
    "knife": ("刀", "把"),
    "spoon": ("勺子", "把"),
    "bowl": ("碗", "个"),
    "banana": ("香蕉", "根"),
    "apple": ("苹果", "个"),
    "sandwich": ("三明治", "个"),
    "orange": ("橙子", "个"),
    "broccoli": ("西兰花", "棵"),
    "carrot": ("胡萝卜", "根"),
    "hot dog": ("热狗", "个"),
    "pizza": ("披萨", "个"),
    "donut": ("甜甜圈", "个"),
    "cake": ("蛋糕", "个"),
    "chair": ("椅子", "把"),
    "couch": ("沙发", "张"),
    "bed": ("床", "张"),
    "dining table": ("餐桌", "张"),
    "tv": ("电视", "台"),
    "laptop": ("笔记本电脑", "台"),
    "mouse": ("鼠标", "个"),
    "keyboard": ("键盘", "个"),
    "cell phone": ("手机", "部"),
    "book": ("书", "本"),
    "clock": ("钟", "个"),
    "teddy bear": ("玩偶熊", "只"),
}
