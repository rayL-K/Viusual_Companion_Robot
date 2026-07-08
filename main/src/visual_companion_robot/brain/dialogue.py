"""对话管理器。

对话管理器负责维护一轮人机交互的输入、生成回复和动作意图。它不
直接访问麦克风、摄像头或 Live2D 渲染器，而是通过运行时消息与其他
模块通信，从而保持核心决策逻辑可测试、可替换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DialogueTurn:
    """一轮对话的结构化记录。

    参考 Open-LLM-VTuber 的 SentenceOutput 设计：
    - ``display_text``：展示给用户的文本（可含表情符号等 UI 元素）
    - ``tts_text``：发送给 TTS 引擎的纯文本
    二者可不同，例如 display_text 带颜文字但 tts_text 只保留语音内容。
    """

    user_text: str
    assistant_text: str = ""
    display_text: str = ""
    tts_text: str = ""
    emotion: str = "neutral"
    actions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 向后兼容：未设置 display/tts 时回退到 assistant_text
        if not self.display_text:
            self.display_text = self.assistant_text
        if not self.tts_text:
            self.tts_text = self.assistant_text


@dataclass
class DialogueContext:
    """Brain 维护的上下文状态，包含最新视觉感知摘要。"""

    last_scene: str = ""
    last_activity: str = ""
    last_emotion: str = "neutral"
    person_count: int = 0
    history: List[DialogueTurn] = field(default_factory=list)

    def update_from_perception(self, frame: Dict[str, Any]) -> None:
        """从 PerceptionFrame 字典同步视觉上下文。"""

        self.last_scene = str(frame.get("scene_caption") or self.last_scene)
        self.last_activity = str(frame.get("person_activity") or self.last_activity)
        self.last_emotion = str(frame.get("emotion_impression") or self.last_emotion)
        self.person_count = int(frame.get("person_count") or self.person_count)

    def build_llm_context(self) -> str:
        """构建传给 LLM 的视觉上下文摘要。"""

        parts = []
        if self.last_scene:
            parts.append(f"当前场景: {self.last_scene}")
        if self.last_activity:
            parts.append(f"用户活动: {self.last_activity}")
        if self.person_count > 0:
            parts.append(f"画面中有 {self.person_count} 人")
        if self.last_emotion:
            parts.append(f"用户情绪: {self.last_emotion}")
        return "\n".join(parts) if parts else ""

