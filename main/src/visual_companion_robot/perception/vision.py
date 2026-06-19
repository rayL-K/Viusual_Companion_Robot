"""PerceptionFrame 数据结构 — 感知模块唯一对外数据契约。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class DetectedObject:
    label: str
    confidence: float = 1.0
    bbox: Optional[List[float]] = None


@dataclass
class PerceptionFrame:
    timestamp: str = ""
    frame_width: int = 0
    frame_height: int = 0

    scene_caption: str = ""
    person_activity: str = ""
    person_count: int = 0
    emotion_impression: str = ""

    objects: List[DetectedObject] = field(default_factory=list)
    objects_detected: List[str] = field(default_factory=list)
    scene_raw: str = ""

    frame_base64: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "scene_caption": self.scene_caption,
            "person_activity": self.person_activity,
            "person_count": self.person_count,
            "emotion_impression": self.emotion_impression,
            "objects_detected": self.objects_detected,
            "objects": [{"label": o.label, "confidence": o.confidence} for o in self.objects],
        }

    def summary(self) -> str:
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
    import cv2
    _, buffer = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buffer).decode("ascii")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
