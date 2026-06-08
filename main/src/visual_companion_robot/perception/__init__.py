"""感知模块。

该包负责把摄像头和麦克风输入转换成更高层的语义信息。视觉感知以
Moondream 2 为核心，输出自然语言场景描述；语音感知通过 sherpa-onnx
实现离线 ASR。
"""

from .vision import PerceptionFrame, DetectedObject, encode_frame_to_base64, now_iso
from .scene_analyzer import SceneAnalyzer
from .asr_interface import ASRInterface, create_asr_engine
from .sherpa_onnx_asr import SherpaOnnxASR
from .vad import VoiceActivityDetector, VADConfig, VAD_SPEECH_START, VAD_SPEECH_END

__all__ = [
    "PerceptionFrame",
    "DetectedObject",
    "SceneAnalyzer",
    "ASRInterface",
    "SherpaOnnxASR",
    "create_asr_engine",
    "VoiceActivityDetector",
    "VADConfig",
    "VAD_SPEECH_START",
    "VAD_SPEECH_END",
    "encode_frame_to_base64",
    "now_iso",
]

