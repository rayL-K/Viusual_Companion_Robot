"""音频播放模块。

该模块后续负责播放 TTS 输出，并向 Live2D 嘴型同步模块提供音量或
播放时间轴。当前只定义播放状态，便于后续测试流程串联。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlaybackState:
    """当前音频播放状态。"""

    is_playing: bool = False
    elapsed_sec: float = 0.0
    rms_volume: float = 0.0

