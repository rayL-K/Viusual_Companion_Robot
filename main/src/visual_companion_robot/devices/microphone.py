"""麦克风适配器。

该模块后续负责采集用户语音，并把音频块交给 VAD/ASR 模块。这里保持
设备输入和语音识别解耦，便于替换 USB 麦克风、板载声卡或远程音频源。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AudioChunk:
    """一段连续麦克风音频。"""

    sample_rate: int
    channels: int
    timestamp_sec: float
    pcm_bytes: bytes = b""

