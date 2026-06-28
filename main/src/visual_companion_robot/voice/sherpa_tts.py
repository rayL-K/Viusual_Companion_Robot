"""sherpa-onnx VITS TTS backend for lightweight local speech synthesis."""

from __future__ import annotations

import importlib.util
import logging
import tarfile
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from visual_companion_robot.speech.tts_interface import TTSInterface
from visual_companion_robot.integrations.model_assets import download_tar_bz2, extract_tar_safely

logger = logging.getLogger(__name__)

_MODEL_URLS = {
    "vits-zh": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-zh-aishell3.tar.bz2",
}


class SherpaOnnxTTS:
    """Manage one sherpa-onnx VITS model and return floating-point samples."""

    def __init__(
        self,
        model_dir: Optional[str] = None,
        model_id: str = "vits-zh",
        num_threads: int = 2,
    ) -> None:
        self._model_id = model_id
        self._model_dir = Path(model_dir or "main/models/tts/sherpa-onnx")
        self._num_threads = max(1, int(num_threads))
        self._tts = None

    def load(self) -> None:
        if self._tts is not None:
            return
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("需要 sherpa-onnx: pip install sherpa-onnx") from exc

        model_root = self._ensure_model()
        model_file = self._find_model_file(model_root)
        if model_file is None:
            raise RuntimeError(f"sherpa-onnx 模型缺少 ONNX 文件: {model_root}")
        tokens_file = self._require_model_file(model_root, "tokens.txt")
        lexicon_file = self._require_model_file(model_root, "lexicon.txt")
        vits = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(model_file),
            tokens=str(tokens_file),
            lexicon=str(lexicon_file),
        )
        model = sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=self._num_threads)
        rule_fsts = ",".join(
            str(path)
            for name in ("phone.fst", "date.fst", "number.fst")
            if (path := model_root / name).is_file()
        )
        config = sherpa_onnx.OfflineTtsConfig(model=model, rule_fsts=rule_fsts)
        self._tts = sherpa_onnx.OfflineTts(config)
        logger.info("sherpa-onnx TTS 已加载: %s", model_file)

    def is_loaded(self) -> bool:
        return self._tts is not None

    def model_root(self) -> Optional[Path]:
        """Return the installed model root without triggering a download."""

        return self._find_model_root()

    def environment_status(self) -> dict[str, object]:
        model_root = self.model_root()
        dependency_ready = importlib.util.find_spec("sherpa_onnx") is not None
        ok = dependency_ready and model_root is not None
        messages = []
        if not dependency_ready:
            messages.append("缺少 sherpa-onnx Python 依赖")
        if model_root is None:
            messages.append("本地 VITS 模型尚未下载；首次使用会自动下载")
        if ok:
            messages.append("本地 sherpa-onnx VITS 可用")
        return {
            "ok": ok,
            "backend": "sherpa_onnx",
            "loaded": self.is_loaded(),
            "model_path": str(model_root or self._model_dir.resolve()),
            "message": "；".join(messages),
        }

    def release(self) -> bool:
        was_loaded = self._tts is not None
        self._tts = None
        return was_loaded

    def synthesize(self, text: str, sid: int = 0, speed: float = 1.0) -> tuple[np.ndarray, int]:
        if self._tts is None:
            raise RuntimeError("sherpa-onnx TTS 未加载")
        clean_text = str(text).strip()
        if not clean_text:
            raise ValueError("TTS 文本不能为空")
        audio = self._tts.generate(clean_text, sid=int(sid), speed=max(0.25, float(speed)))
        samples = np.asarray(audio.samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            raise RuntimeError("sherpa-onnx 返回了空音频")
        return samples, int(audio.sample_rate)

    def _ensure_model(self) -> Path:
        existing = self._find_model_root()
        if existing is not None:
            return existing

        url = _MODEL_URLS.get(self._model_id)
        if not url:
            raise RuntimeError(f"未知模型: {self._model_id}，可选: {list(_MODEL_URLS)}")
        self._model_dir.mkdir(parents=True, exist_ok=True)
        logger.info("正在下载 TTS 模型: %s", url)
        self._download(url)

        downloaded = self._find_model_root()
        if downloaded is None:
            raise RuntimeError(f"下载完成但模型文件不完整: {self._model_dir}")
        return downloaded

    def _find_model_root(self) -> Optional[Path]:
        if not self._model_dir.is_dir():
            return None
        for tokens_file in sorted(self._model_dir.rglob("tokens.txt")):
            root = tokens_file.parent
            if (root / "lexicon.txt").is_file() and self._find_model_file(root) is not None:
                return root
        return None

    @staticmethod
    def _find_model_file(model_root: Path) -> Optional[Path]:
        preferred_names = (
            "model.int8.onnx",
            "vits-aishell3.int8.onnx",
            "model.onnx",
            "vits-aishell3.onnx",
        )
        for name in preferred_names:
            path = model_root / name
            if path.is_file():
                return path
        candidates = sorted(model_root.glob("*.int8.onnx")) or sorted(model_root.glob("*.onnx"))
        return candidates[0] if candidates else None

    @staticmethod
    def _require_model_file(model_root: Path, name: str) -> Path:
        path = model_root / name
        if not path.is_file():
            raise RuntimeError(f"sherpa-onnx 模型缺少 {name}: {model_root}")
        return path

    def _download(self, url: str) -> None:
        download_tar_bz2(url, self._model_dir)

    def _extract_safely(self, bundle: tarfile.TarFile) -> None:
        extract_tar_safely(bundle, self._model_dir)


class SherpaOnnxTTSAdapter(TTSInterface):
    """Expose sherpa-onnx through the project's file-based TTS contract."""

    def __init__(self, engine: Optional[SherpaOnnxTTS] = None) -> None:
        self._engine = engine or SherpaOnnxTTS()

    def generate_audio(self, text: str, **kwargs) -> str:
        self._engine.load()
        samples, sample_rate = self._engine.synthesize(
            text,
            sid=int(kwargs.get("sid", 0)),
            speed=float(kwargs.get("speed", 1.0)),
        )
        output_path = self.temp_wav_path("sherpa_tts")
        pcm = np.clip(samples, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2").tobytes()
        try:
            with wave.open(output_path, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(pcm)
        except Exception:
            Path(output_path).unlink(missing_ok=True)
            raise
        return output_path
