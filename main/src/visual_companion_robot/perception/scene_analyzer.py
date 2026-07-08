"""使用 RK3588 NPU 生成确定性的本地场景语义。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .detector import YoloDetector
from .vision import DetectedObject, PerceptionFrame, now_iso


@dataclass(frozen=True)
class SceneAnalyzerConfig:
    yolo_model_path: str
    conf_threshold: float = 0.5


class SceneAnalyzer:
    """管理单个 YOLO 检测器并把检测结果转换为对话上下文。"""

    def __init__(self, config: SceneAnalyzerConfig, detector: YoloDetector | None = None) -> None:
        self._config = config
        self._detector = detector or YoloDetector(
            model_path=config.yolo_model_path,
            conf_threshold=config.conf_threshold,
        )

    def load(self) -> None:
        self._detector.load()

    def unload(self) -> None:
        self._detector.unload()

    def is_loaded(self) -> bool:
        return self._detector.is_loaded()

    def analyze(self, frame_bgr: np.ndarray) -> PerceptionFrame:
        if frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            raise ValueError("场景分析只接受 BGR 三通道图像")

        detections = self._detector.detect(frame_bgr)
        labels = [item.class_name for item in detections.detections]
        person_count = labels.count("person")
        return PerceptionFrame(
            timestamp=now_iso(),
            frame_width=detections.frame_width,
            frame_height=detections.frame_height,
            scene_caption=self._detector.describe(detections),
            person_activity=_infer_activity(labels, person_count),
            person_count=person_count,
            objects=[
                DetectedObject(
                    label=item.class_name,
                    confidence=item.confidence,
                    bbox=[item.x1, item.y1, item.x2, item.y2],
                )
                for item in detections.detections
            ],
            objects_detected=labels,
        )


def _infer_activity(labels: list[str], person_count: int) -> str:
    """只根据同时出现的物体给出保守活动提示，不引入额外模型。"""

    if person_count <= 0:
        return ""
    label_set = set(labels)
    if label_set & {"laptop", "keyboard", "mouse"}:
        return "人物可能正在使用电脑"
    if "cell phone" in label_set:
        return "人物可能正在使用手机"
    if "book" in label_set:
        return "人物可能正在阅读"
    if label_set & {"cup", "bottle"}:
        return "人物身边有饮品"
    return "画面中有人"
