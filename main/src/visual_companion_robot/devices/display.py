"""显示设备适配器。

该模块描述机器人图形界面的显示目标。开发阶段可以通过 VNC 调试，
比赛展示阶段则可以切换到 Firefly 外接 HDMI 屏幕或全屏窗口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DisplayTarget:
    """图形界面输出目标。"""

    display_name: str = ":0"
    fullscreen: bool = False
    width: Optional[int] = None
    height: Optional[int] = None

