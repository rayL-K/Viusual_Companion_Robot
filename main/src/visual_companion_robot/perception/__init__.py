"""感知模块的惰性导出，避免模型模块在无关命令中提前加载。"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "PerceptionFrame": ("vision", "PerceptionFrame"),
    "DetectedObject": ("vision", "DetectedObject"),
    "encode_frame_to_base64": ("vision", "encode_frame_to_base64"),
    "now_iso": ("vision", "now_iso"),
    "SceneAnalyzer": ("scene_analyzer", "SceneAnalyzer"),
    "SceneAnalyzerConfig": ("scene_analyzer", "SceneAnalyzerConfig"),
    "BoardVisionService": ("vision_service", "BoardVisionService"),
    "VisionServiceConfig": ("vision_service", "VisionServiceConfig"),
    "ASRInterface": ("asr_interface", "ASRInterface"),
    "create_asr_engine": ("asr_interface", "create_asr_engine"),
    "SherpaOnnxASR": ("sherpa_onnx_asr", "SherpaOnnxASR"),
    "OfflineAsrResult": ("offline_asr_service", "OfflineAsrResult"),
    "OfflineAsrService": ("offline_asr_service", "OfflineAsrService"),
    "VoiceActivityDetector": ("vad", "VoiceActivityDetector"),
    "VADConfig": ("vad", "VADConfig"),
    "VAD_SPEECH_START": ("vad", "VAD_SPEECH_START"),
    "VAD_SPEECH_END": ("vad", "VAD_SPEECH_END"),
    "FerPlusEmotionRecognizer": ("emotion", "FerPlusEmotionRecognizer"),
    "EmotionResult": ("emotion", "EmotionResult"),
    "YoloDetector": ("detector", "YoloDetector"),
    "PerceptionLoop": ("perception_loop", "PerceptionLoop"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute_name)
    globals()[name] = value
    return value


__all__ = sorted(_EXPORTS)
