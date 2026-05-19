"""对话管理器。

对话管理器负责维护一轮人机交互的输入、生成回复和动作意图。它不
直接访问麦克风、摄像头或 Live2D 渲染器，而是通过运行时消息与其他
模块通信，从而保持核心决策逻辑可测试、可替换。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DialogueTurn:
    """一轮对话的结构化记录。"""

    user_text: str
    assistant_text: str = ""
    emotion: str = "neutral"
    actions: list[str] = field(default_factory=list)

