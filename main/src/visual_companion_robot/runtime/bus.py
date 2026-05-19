"""运行时消息总线。

消息总线用于在视觉、语音、脑控、TTS 和 UI 模块之间传递事件。当前
只定义通用消息结构，后续可以替换为队列、多进程管道或异步事件循环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RobotEvent:
    """模块之间传递的一条事件。"""

    event_type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)

