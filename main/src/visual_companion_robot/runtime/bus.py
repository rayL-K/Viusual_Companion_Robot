"""运行时消息总线。

消息总线用于在视觉、语音、脑控、TTS 和 UI 模块之间传递事件。当前
只定义通用消息结构，后续可以替换为队列、多进程管道或异步事件循环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---- 事件类型常量 ----
EVENT_VISION_FRAME = "vision.frame"
"""视觉感知帧更新。payload 为 PerceptionFrame.to_dict()。"""
EVENT_VISION_SCENE = "vision.scene"
"""场景描述更新。payload 含 scene_caption / person_activity。"""
EVENT_VISION_PERSON = "vision.person"
"""人物检测事件。payload 含 person_count / emotion_impression。"""
EVENT_SPEECH_RESULT = "speech.result"
"""语音识别结果。payload 含 text / is_final。"""
EVENT_BRAIN_REPLY = "brain.reply"
"""大脑决策输出。payload 含 text / emotion / actions。"""
EVENT_TTS_START = "tts.start"
"""语音合成开始。"""
EVENT_TTS_END = "tts.end"
"""语音合成结束。"""


@dataclass
class RobotEvent:
    """模块之间传递的一条事件。"""

    event_type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)

