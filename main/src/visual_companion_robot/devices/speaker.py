"""扬声器适配器。

该模块后续负责播放 TTS 生成的音频，并向 UI 模块提供播放状态。嘴型
同步不应直接读取播放器内部状态，而应通过统一的音量或时间轴事件驱动。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeakerOutput:
    """一次音频播放请求。"""

    wav_path: str
    volume: float = 1.0

