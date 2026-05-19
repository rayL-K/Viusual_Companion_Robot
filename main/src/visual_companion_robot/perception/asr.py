"""语音识别模块。

该模块后续接入离线 ASR，例如 sherpa-onnx、SenseVoice 或 Paraformer。
它只输出文本和置信度，不负责生成回复，也不直接控制 TTS 或 Live2D。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeechRecognitionResult:
    """一次语音识别结果。"""

    text: str
    confidence: float = 0.0
    is_final: bool = True

