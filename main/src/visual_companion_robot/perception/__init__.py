"""感知模块。

该包负责把摄像头和麦克风输入转换成更高层的语义信息。视觉感知以
Moondream 2 为核心，输出自然语言场景描述；语音感知后续接入 ASR。
"""

from .vision import PerceptionFrame, DetectedObject, encode_frame_to_base64, now_iso
from .scene_analyzer import SceneAnalyzer

__all__ = [
    "PerceptionFrame",
    "DetectedObject",
    "SceneAnalyzer",
    "encode_frame_to_base64",
    "now_iso",
]

