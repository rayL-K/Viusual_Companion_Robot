"""文本转语音模块。

该模块后续接入离线 TTS，例如 Piper、VITS 或 sherpa-onnx TTS。它只负责
把文本转换为音频文件或音频流，不直接控制扬声器和 Live2D。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeechSynthesisRequest:
    """一次文本转语音请求。"""

    text: str
    voice: str = "default"
    emotion: str = "neutral"

