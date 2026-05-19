"""视觉感知模块。

该模块后续负责接入摄像头目标检测、用户位置估计和基础表情/姿态识别。
视觉结果应以结构化事件输出，供脑控模块和 Live2D 注视/转头动作使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class VisionObservation:
    """一帧视觉感知摘要。"""

    has_person: bool
    target_x: Optional[float] = None
    target_y: Optional[float] = None
    confidence: float = 0.0

