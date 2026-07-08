"""Light-ASD 本地主动说话人推理。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from visual_companion_robot.integrations.model_runtime import OnnxEngine


SAMPLE_RATE = 16_000
MIN_AUDIO_SECONDS = 0.8
MAX_AUDIO_SECONDS = 4.0
MIN_SOURCE_FRAMES = 4


class ActiveSpeakerError(RuntimeError):
    """同步音画片段不满足主动说话人推理契约。"""


class ActiveSpeakerInputError(ActiveSpeakerError):
    """客户端提供的同步音画片段无效。"""


class ActiveSpeakerBusyError(ActiveSpeakerError):
    """板端已有主动说话人任务在执行。"""


class FaceTrackLike(Protocol):
    track_id: int
    crops: tuple[np.ndarray, ...]
    profile_id: str | None
    name: str | None


@dataclass(frozen=True)
class SpeakerCandidate:
    track_id: int
    confidence: float
    profile_id: str | None
    name: str | None


class ActiveSpeakerRecognizer:
    """接受同步 PCM 与人脸轨迹，输出保守的主动说话人结论。"""

    def __init__(self, model_path: Path, engine: OnnxEngine | None = None) -> None:
        self._model_path = model_path
        self._engine = engine or OnnxEngine()
        self._lock = threading.Lock()

    def load(self) -> None:
        if not self._model_path.is_file():
            raise ActiveSpeakerError(f"Light-ASD 模型不存在：{self._model_path}")
        self._engine.load(str(self._model_path))

    def is_loaded(self) -> bool:
        return self._engine.is_loaded()

    def close(self) -> None:
        self._engine.unload()

    def analyze(self, pcm16: np.ndarray, tracks: list[FaceTrackLike]) -> dict:
        if not self._lock.acquire(blocking=False):
            raise ActiveSpeakerBusyError("主动说话人服务繁忙，请稍后重试")
        try:
            return self._analyze(pcm16, tracks)
        finally:
            self._lock.release()

    def _analyze(self, pcm16: np.ndarray, tracks: list[FaceTrackLike]) -> dict:
        audio = np.asarray(pcm16, dtype=np.int16).reshape(-1)
        minimum_samples = round(SAMPLE_RATE * MIN_AUDIO_SECONDS)
        if audio.size < minimum_samples:
            raise ActiveSpeakerInputError("主动说话人音频至少需要 0.8 秒")
        audio = audio[-round(SAMPLE_RATE * MAX_AUDIO_SECONDS):]
        if not tracks:
            return _unknown("no_face_track")

        mfcc = _mfcc(audio)
        video_frame_count = mfcc.shape[0] // 4
        if video_frame_count < 1:
            raise ActiveSpeakerInputError("音频过短，无法与视频帧对齐")
        mfcc = mfcc[:video_frame_count * 4]

        candidates: list[SpeakerCandidate] = []
        for track in tracks:
            if len(track.crops) < MIN_SOURCE_FRAMES:
                continue
            face_frames = _resample_crops(track.crops, video_frame_count)
            outputs = self._engine.run(
                output_names=[],
                input_feed={
                    "audio_mfcc": mfcc[np.newaxis, ...].astype(np.float32, copy=False),
                    "face_frames": face_frames[np.newaxis, ...].astype(np.float32, copy=False),
                },
            )
            if not outputs:
                raise ActiveSpeakerError("Light-ASD 没有返回结果")
            probabilities = np.asarray(outputs[0], dtype=np.float32).reshape(-1)
            if probabilities.size != video_frame_count or not np.all(np.isfinite(probabilities)):
                raise ActiveSpeakerError("Light-ASD 输出形状或数值无效")
            confidence = float(np.mean(probabilities))
            candidates.append(
                SpeakerCandidate(track.track_id, confidence, track.profile_id, track.name)
            )

        if not candidates:
            return _unknown("insufficient_face_frames")
        candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
        best = candidates[0]
        runner_up = candidates[1].confidence if len(candidates) > 1 else 0.0
        threshold = 0.60 if len(candidates) > 1 else 0.55
        if best.confidence < threshold:
            return _result("unknown", "low_confidence", candidates)
        if len(candidates) > 1 and best.confidence - runner_up < 0.08:
            return _result("unknown", "ambiguous_candidates", candidates)
        result = _result("confirmed", "audio_visual_consistency", candidates)
        result["speaker"] = {
            "track_id": best.track_id,
            "confidence": round(best.confidence, 4),
            "profile_id": best.profile_id,
            "name": best.name,
        }
        return result


def _mfcc(audio: np.ndarray) -> np.ndarray:
    try:
        import python_speech_features
    except ImportError as exc:
        raise ActiveSpeakerError("板端缺少 python_speech_features") from exc
    return np.asarray(
        python_speech_features.mfcc(
            audio,
            SAMPLE_RATE,
            numcep=13,
            winlen=0.025,
            winstep=0.010,
        ),
        dtype=np.float32,
    )


def _resample_crops(crops: tuple[np.ndarray, ...], count: int) -> np.ndarray:
    indices = np.rint(np.linspace(0, len(crops) - 1, count)).astype(np.int32)
    selected = [np.asarray(crops[index], dtype=np.uint8) for index in indices]
    if any(frame.shape != (112, 112) for frame in selected):
        raise ActiveSpeakerInputError("人脸轨迹必须由 112×112 灰度帧组成")
    return np.stack(selected)


def _unknown(reason: str) -> dict:
    return {"status": "unknown", "reason": reason, "candidates": []}


def _result(status: str, reason: str, candidates: list[SpeakerCandidate]) -> dict:
    return {
        "status": status,
        "reason": reason,
        "candidates": [
            {
                "track_id": item.track_id,
                "confidence": round(item.confidence, 4),
                "profile_id": item.profile_id,
                "name": item.name,
            }
            for item in candidates
        ],
    }
