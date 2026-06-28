"""感知模块。

该包负责把摄像头和麦克风输入转换成更高层的语义信息。摄像头循环依赖
OpenCV，因此使用惰性导入，避免只使用情绪、VAD 等组件时被无关依赖阻塞。
"""

from .vision import PerceptionFrame, DetectedObject, encode_frame_to_base64, now_iso
from .scene_analyzer import SceneAnalyzer, SceneAnalyzerConfig
from .asr_interface import ASRInterface, create_asr_engine
from .sherpa_onnx_asr import SherpaOnnxASR
from .offline_asr_service import OfflineAsrResult, OfflineAsrService
from .vad import VoiceActivityDetector, VADConfig, VAD_SPEECH_START, VAD_SPEECH_END
from .emotion import FerPlusEmotionRecognizer, EmotionResult
from .detector import YoloDetector


def __getattr__(name: str):
    if name == "PerceptionLoop":
        from .perception_loop import PerceptionLoop

        return PerceptionLoop
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "PerceptionFrame",
    "DetectedObject",
    "SceneAnalyzer",
    "ASRInterface",
    "SherpaOnnxASR",
    "OfflineAsrResult",
    "OfflineAsrService",
    "create_asr_engine",
    "VoiceActivityDetector",
    "VADConfig",
    "VAD_SPEECH_START",
    "VAD_SPEECH_END",
    "PerceptionLoop",
    "FerPlusEmotionRecognizer",
    "EmotionResult",
    "YoloDetector",
    "encode_frame_to_base64",
    "now_iso",
]

