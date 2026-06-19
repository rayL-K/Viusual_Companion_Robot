"""sherpa-onnx TTS 后端 — 轻量本地语音合成。

在 RK3588 CPU 上可用，模型约 50-200MB，无需 GPU。
比 VoxCPM2 (2B) 轻量得多，适合板端部署。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from visual_companion_robot.speech.tts_interface import TTSInterface, TTSVoice

logger = logging.getLogger(__name__)

# sherpa-onnx 预训练 TTS 模型下载地址
_MODEL_URLS = {
    "vits-zh": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-zh-aishell3.tar.bz2",
    "matcha-zh": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/matcha-zh-aishell3.tar.bz2",
}


class SherpaOnnxTTS:
    """sherpa-onnx TTS 引擎。

    支持中文语音合成，模型自动下载缓存。
    所有资源通过 OfflineTts API 管理，支持 VITS / Matcha-TTS 等架构。

    Args:
        model_dir: 模型存放目录，默认 main/models/tts/sherpa-onnx/。
        model_id: 模型标识，默认 "vits-zh"。
        voice: 音色参数。
    """

    def __init__(
        self,
        model_dir: Optional[str] = None,
        model_id: str = "vits-zh",
        voice: TTSVoice = TTSVoice.FEMALE_ZH,
    ) -> None:
        self._model_id = model_id
        self._voice = voice
        self._model_dir = Path(model_dir or "main/models/tts/sherpa-onnx")
        self._tts = None
        self._loaded = False

    def load(self) -> None:
        """加载 TTS 模型。首次调用时自动下载。"""

        if self._loaded:
            return

        try:
            import sherpa_onnx
        except ImportError:
            raise RuntimeError("需要 sherpa-onnx: pip install sherpa-onnx")

        model_path = self._ensure_model()
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=model_path,
                ),
            ),
        )

        self._tts = sherpa_onnx.OfflineTts(config)
        self._loaded = True
        logger.info("sherpa-onnx TTS 已加载: %s", model_path)

    def is_loaded(self) -> bool:
        return self._loaded

    def synthesize(self, text: str, sid: int = 0, speed: float = 1.0) -> tuple[bytes, int]:
        """合成语音。

        Args:
            text: 要合成的文本。
            sid: 说话人 ID（多说话人模型使用）。
            speed: 语速倍率。

        Returns:
            (wav_bytes, sample_rate)。
        """
        if not self._loaded or self._tts is None:
            raise RuntimeError("sherpa-onnx TTS 未加载")

        audio = self._tts.generate(text, sid=sid, speed=speed)
        samples = audio.samples
        sample_rate = audio.sample_rate

        import numpy as np
        wav_bytes = np.array(samples, dtype=np.float32).tobytes()
        return wav_bytes, sample_rate

    def _ensure_model(self) -> str:
        """确保模型文件存在，不存在则自动下载。"""

        self._model_dir.mkdir(parents=True, exist_ok=True)
        model_file = self._model_dir / f"{self._model_id}.onnx"

        if model_file.is_file():
            return str(model_file)

        url = _MODEL_URLS.get(self._model_id)
        if not url:
            raise RuntimeError(f"未知模型: {self._model_id}，可选: {list(_MODEL_URLS.keys())}")

        logger.info("正在下载 TTS 模型: %s", url)
        self._download(url)

        if not model_file.is_file():
            raise RuntimeError(f"下载完成但模型文件未找到: {model_file}")
        return str(model_file)

    def _download(self, url: str) -> None:
        """下载并解压模型。"""

        import tarfile
        import urllib.request
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".tar.bz2", delete=False) as tmp:
            tmp_path = tmp.name
            urllib.request.urlretrieve(url, tmp_path)

        with tarfile.open(tmp_path, "r:bz2") as tar:
            tar.extractall(path=self._model_dir)

        os.unlink(tmp_path)


# ── TTSInterface 适配器 ───────────────────────────────────────────

class SherpaOnnxTTSAdapter(TTSInterface):
    """sherpa-onnx TTS 的 TTSInterface 适配器。"""

    def __init__(self, engine: SherpaOnnxTTS) -> None:
        self._engine = engine

    def synthesize(self, text: str, voice: TTSVoice = TTSVoice.FEMALE_ZH) -> tuple[bytes, int]:
        self._engine.load()
        sid = 0
        return self._engine.synthesize(text, sid=sid)

    def get_voices(self) -> list[TTSVoice]:
        return [TTSVoice.FEMALE_ZH]

    @property
    def is_ready(self) -> bool:
        return self._engine.is_loaded()
