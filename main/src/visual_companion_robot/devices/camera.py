"""摄像头适配器。

该模块后续负责打开 RK3588 板端摄像头、读取图像帧，并把原始帧转换
成视觉感知模块可处理的统一结构。当前只定义帧对象，暂不绑定具体 SDK。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CameraFrame:
    """摄像头单帧数据描述。"""

    width: int
    height: int
    timestamp_sec: float
    pixel_format: str = "unknown"

