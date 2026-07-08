"""基于 sherpa-onnx SenseVoice 的离线语音识别后端。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from visual_companion_robot.integrations.model_assets import download_tar_bz2

from .asr_interface import ASRInterface, ASR_SAMPLE_RATE

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ROOT = Path("main/models/asr")
SENSE_VOICE_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"
)


class SherpaOnnxASR(ASRInterface):
    """懒加载 SenseVoice INT8 模型并识别 16 kHz 单声道音频。"""

    def __init__(
        self,
        model_root: Optional[str] = None,
        provider: str = "cpu",
        language: str = "zh",
        num_threads: int = 2,
    ) -> None:
        self._model_root = Path(model_root) if model_root else DEFAULT_MODEL_ROOT
        self._provider = provider
        self._language = language
        self._num_threads = max(1, int(num_threads))
        self._recognizer = None

    def load(self) -> None:
        if self._recognizer is not None:
            return
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("需要 sherpa-onnx: pip install sherpa-onnx") from exc

        model_dir = self._ensure_model()
        model_file = self._find_model_file(model_dir)
        tokens_file = model_dir / "tokens.txt"
        if model_file is None or not tokens_file.is_file():
            raise RuntimeError(f"SenseVoice 模型文件不完整: {model_dir}")

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_file),
            tokens=str(tokens_file),
            num_threads=self._num_threads,
            provider=self._provider,
            language=self._language,
            use_itn=True,
        )
        logger.info("sherpa-onnx SenseVoice 已加载: %s", model_file)

    def is_loaded(self) -> bool:
        return self._recognizer is not None

    def model_path(self) -> Optional[Path]:
        model_dir = self._find_model_dir()
        return self._find_model_file(model_dir) if model_dir else None

    def transcribe_np(self, audio: np.ndarray) -> str:
        self.load()
        samples = normalize_audio(audio)
        if samples.size == 0:
            raise ValueError("ASR 音频不能为空")

        stream = self._recognizer.create_stream()
        stream.accept_waveform(ASR_SAMPLE_RATE, samples)
        self._recognizer.decode_stream(stream)
        return str(stream.result.text or "").strip()

    def _ensure_model(self) -> Path:
        existing = self._find_model_dir()
        if existing is not None:
            return existing

        logger.info("正在下载 SenseVoice INT8 模型: %s", SENSE_VOICE_MODEL_URL)
        download_tar_bz2(SENSE_VOICE_MODEL_URL, self._model_root)
        downloaded = self._find_model_dir()
        if downloaded is None:
            raise RuntimeError(f"下载完成但 SenseVoice 模型不完整: {self._model_root}")
        return downloaded

    def _find_model_dir(self) -> Optional[Path]:
        if not self._model_root.is_dir():
            return None
        for tokens_file in sorted(self._model_root.rglob("tokens.txt")):
            model_dir = tokens_file.parent
            if self._find_model_file(model_dir) is not None:
                return model_dir
        return None

    @staticmethod
    def _find_model_file(model_dir: Path) -> Optional[Path]:
        for name in ("model.int8.onnx", "model.onnx"):
            path = model_dir / name
            if path.is_file():
                return path
        candidates = sorted(model_dir.glob("*.int8.onnx")) or sorted(model_dir.glob("*.onnx"))
        return candidates[0] if candidates else None


def normalize_audio(audio: np.ndarray) -> np.ndarray:
    """把 int16/float 音频转换为有限的 float32 [-1, 1] 一维数组。"""

    array = np.asarray(audio).reshape(-1)
    if np.issubdtype(array.dtype, np.integer):
        limit = float(max(abs(np.iinfo(array.dtype).min), np.iinfo(array.dtype).max))
        normalized = array.astype(np.float32) / limit
    else:
        normalized = array.astype(np.float32)
    if not np.all(np.isfinite(normalized)):
        raise ValueError("ASR 音频包含非有限数值")
    return np.clip(normalized, -1.0, 1.0)
