"""PCM16 请求的 VAD 校验与离线 ASR 编排。"""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any, Dict, Optional

import numpy as np

from .asr_interface import ASR_SAMPLE_RATE
from .sherpa_onnx_asr import SherpaOnnxASR
from .vad import VoiceActivityDetector

MIN_AUDIO_DURATION_MS = 300
MAX_AUDIO_DURATION_MS = 30_000
MIN_SPEECH_RATIO = 0.08


@dataclass(frozen=True)
class OfflineAsrResult:
    text: str
    speech_detected: bool
    speech_ratio: float
    duration_ms: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class OfflineAsrService:
    """验证 PCM16 音频，在检测到语音后串行调用 SenseVoice。"""

    def __init__(
        self,
        engine: Optional[SherpaOnnxASR] = None,
        vad: Optional[VoiceActivityDetector] = None,
    ) -> None:
        self._engine = engine or SherpaOnnxASR()
        self._vad = vad or VoiceActivityDetector()
        self._decode_lock = Lock()

    def health(self) -> Dict[str, Any]:
        model_path = self._engine.model_path()
        dependency_ready = importlib.util.find_spec("sherpa_onnx") is not None
        vad_ready = self._vad.is_available()
        return {
            "ok": dependency_ready and vad_ready,
            "backend": "sherpa-onnx-sensevoice",
            "sample_rate": ASR_SAMPLE_RATE,
            "dependency_ready": dependency_ready,
            "vad_ready": vad_ready,
            "model_ready": model_path is not None,
            "model_path": str(model_path) if model_path else "",
            "loaded": self._engine.is_loaded(),
        }

    def prepare(self) -> None:
        """显式加载 ASR 模型，供服务启动后后台预热。"""

        with self._decode_lock:
            self._engine.load()

    def transcribe_pcm16(self, pcm_bytes: bytes) -> OfflineAsrResult:
        duration_ms = validate_pcm16(pcm_bytes)
        speech_ratio = self._vad.speech_ratio(pcm_bytes)
        if speech_ratio < MIN_SPEECH_RATIO:
            return OfflineAsrResult("", False, round(speech_ratio, 4), duration_ms)

        trimmed_pcm = self._vad.trim_to_speech(pcm_bytes) if hasattr(self._vad, "trim_to_speech") else pcm_bytes
        if not trimmed_pcm:
            return OfflineAsrResult("", False, round(speech_ratio, 4), duration_ms)
        samples = np.frombuffer(trimmed_pcm, dtype="<i2")
        with self._decode_lock:
            text = self._engine.transcribe_np(samples)
        return OfflineAsrResult(text, True, round(speech_ratio, 4), duration_ms)


def validate_pcm16(pcm_bytes: bytes) -> int:
    if not pcm_bytes or len(pcm_bytes) % 2:
        raise ValueError("ASR 请求必须是非空的 16 位 PCM 单声道音频")
    duration_ms = round(len(pcm_bytes) / 2 / ASR_SAMPLE_RATE * 1000)
    if duration_ms < MIN_AUDIO_DURATION_MS:
        raise ValueError(f"ASR 音频至少需要 {MIN_AUDIO_DURATION_MS} ms")
    if duration_ms > MAX_AUDIO_DURATION_MS:
        raise ValueError(f"ASR 音频不能超过 {MAX_AUDIO_DURATION_MS // 1000} 秒")
    return duration_ms
