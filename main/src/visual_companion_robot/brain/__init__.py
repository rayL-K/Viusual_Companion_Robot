"""对话与决策模块。

该包负责把感知层输入转换成机器人可执行的回复、表情和动作意图。
后续会在这里接入本地小语言模型、角色设定、短期上下文和长期记忆。
"""

from .dialogue import DialogueTurn, DialogueContext

__all__ = ["DialogueTurn", "DialogueContext"]

