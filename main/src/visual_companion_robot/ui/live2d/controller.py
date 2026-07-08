"""Live2D 参数控制器。

该模块负责把机器人状态转换为 Live2D 参数变化，例如表情、转头、眨眼、
呼吸和手势。它应只输出控制意图，具体渲染由窗口或渲染后端完成。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Live2DAction:
    """一次 Live2D 控制动作。"""

    action_type: str
    name: str
    intensity: float = 1.0

