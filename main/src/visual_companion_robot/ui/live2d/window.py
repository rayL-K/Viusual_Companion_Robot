"""Live2D 展示窗口。

该模块后续负责创建桌面窗口或全屏窗口，并把 Live2D 渲染内容输出到
Firefly 的显示设备。窗口层只处理显示，不直接决定机器人说什么。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Live2DWindowConfig:
    """Live2D 窗口运行配置。"""

    title: str = "Visual Companion Robot"
    width: int = 1280
    height: int = 720
    transparent: bool = False
    fullscreen: bool = False

