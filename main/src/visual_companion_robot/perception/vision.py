"""视觉感知模块 — 以 Moondream 2 为核心的场景理解。

该模块不再依赖 MediaPipe 做情绪推断，而是由 Moondream 2 通过 caption/query
接口直接产出自然语言场景描述。PerceptionFrame 是模块唯一的对外数据结构。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class DetectedObject:
    """画面中检测到的物体或人物。"""

    label: str
    confidence: float = 1.0
    bbox: Optional[List[float]] = None


@dataclass
class PerceptionFrame:
    """一帧视觉感知结果。

    每个字段都可以独立为 None，表示本轮未产生该项感知数据。
    调用方按需取用，不要假设所有字段都有值。
    """

    # ---- 元数据 ----
    timestamp: str = ""
    frame_width: int = 0
    frame_height: int = 0

    # ---- Moondream 场景描述 ----
    scene_caption: str = ""
    """自然语言场景描述，例如 "a person sitting on a couch in a living room, smiling"."""

    person_activity: str = ""
    """回答 "What is the person doing?" 的结果。"""

    person_count: int = 0
    """画面中检测到的人数。"""

    emotion_impression: str = ""
    """从画面推断的情绪，例如 "happy" / "neutral" / "surprised"。"""

    # ---- 检测到的物体 ----
    objects: List[DetectedObject] = field(default_factory=list)
    """画面中识别到的物体列表。"""

    # ---- 原始帧（可选，供调试） ----
    frame_base64: str = ""
    """当前帧的 JPEG base64，供日志或前端预览。"""

    def to_dict(self) -> Dict[str, Any]:
        """转换为前端/LLM 可消费的字典。"""

        result: Dict[str, Any] = {
            "timestamp": self.timestamp,
            "scene_caption": self.scene_caption,
            "person_activity": self.person_activity,
            "person_count": self.person_count,
            "emotion_impression": self.emotion_impression,
            "objects": [{"label": o.label, "confidence": o.confidence} for o in self.objects],
        }
        return result

    def summary(self) -> str:
        """生成一行中文摘要，供日志或 Brain 快速消费。"""

        parts = []
        if self.scene_caption:
            parts.append(self.scene_caption)
        if self.person_activity:
            parts.append(f"活动: {self.person_activity}")
        if self.person_count > 0:
            parts.append(f"人数: {self.person_count}")
        if self.emotion_impression:
            parts.append(f"情绪: {self.emotion_impression}")
        return " | ".join(parts) if parts else "（无视觉感知数据）"


def encode_frame_to_base64(frame_bgr, quality: int = 70) -> str:
    """将 OpenCV BGR 帧编码为 base64 JPEG 字符串。"""

    import cv2

    _, buffer = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buffer).decode("ascii")


def now_iso() -> str:
    """返回当前 ISO 时间字符串，作为时间戳。"""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
