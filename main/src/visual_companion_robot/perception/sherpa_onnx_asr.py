"""基于 sherpa-onnx 的离线语音识别后端。

sherpa-onnx 支持多种模型架构（Paraformer、Whisper、SenseVoice 等），
纯 C++ 推理，无需 Python 深度学习框架。

模型文件首次运行时会自动下载到 ``models/asr/`` 目录。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from .asr_interface import ASRInterface

logger = logging.getLogger(__name__)

# 默认模型目录（相对于项目根）
_DEFAULT_MODEL_ROOT = Path("main/models/asr")


class SherpaOnnxASR(ASRInterface):
    """sherpa-onnx 语音识别引擎。

    支持多种预训练模型，自动下载模型文件。

    Args:
        model_type: 模型架构类型，默认 "sense_voice"（多语言）。
            可选："paraformer", "transducer", "whisper", "sense_voice"。
        model_root: 模型文件存放目录。
        provider: 推理后端，默认 "cpu"。RK3588 可用 "npu"（需 RKNN 支持）。
        language: 识别语言，默认 "zh"。
    """

    _SUPPORTED_TYPES = ("paraformer", "transducer", "whisper", "sense_voice")

    def __init__(
        self,
        model_type: str = "sense_voice",
        model_root: Optional[str] = None,
        provider: str = "cpu",
        language: str = "zh",
    ) -> None:
        if model_type not in self._SUPPORTED_TYPES:
            raise ValueError(f"不支持的 model_type：{model_type}，可选：{self._SUPPORTED_TYPES}")

        self._model_type = model_type
        self._model_root = Path(model_root) if model_root else _DEFAULT_MODEL_ROOT
        self._provider = provider
        self._language = language
        self._recognizer = None
        self._load_model()

    # ------------------------------------------------------------------
    # ASRInterface 实现
    # ------------------------------------------------------------------

    def transcribe_np(self, audio: np.ndarray) -> str:
        """识别 numpy 音频数组。

        Args:
            audio: float32 一维数组，采样率 16000。

        Returns:
            识别文本。
        """

        if self._recognizer is None:
            raise RuntimeError("sherpa-onnx 模型未加载")

        # 确保 float32 + 一维
        audio = np.asarray(audio, dtype=np.float32).ravel()
        samples = audio.tolist()

        self._recognizer.accept_waveform(ASR_SAMPLE_RATE, samples)
        result = self._recognizer.get_result()
        return result.text.strip()

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """加载 sherpa-onnx 模型。首次运行会自动下载。"""

        import sherpa_onnx

        self._model_root.mkdir(parents=True, exist_ok=True)

        if self._model_type == "sense_voice":
            self._recognizer = self._create_sense_voice(sherpa_onnx)
        elif self._model_type == "paraformer":
            self._recognizer = self._create_paraformer(sherpa_onnx)
        else:
            raise NotImplementedError(f"暂未实现：{self._model_type}")

        logger.info("sherpa-onnx %s 模型加载完成 [provider=%s]", self._model_type, self._provider)

    def _create_sense_voice(self, sherpa_onnx) -> object:
        """创建 SenseVoice 模型（多语言，推荐中文场景）。"""

        model_dir = str(self._model_root / "sense-voice")

        config = sherpa_onnx.OfflineRecognizerConfig(
            model=sherpa_onnx.OfflineModelConfig(
                sense_voice=sherpa_onnx.OfflineSenseVoiceModelConfig(
                    model=str(Path(model_dir) / "model.onnx"),
                    language=self._language,
                    use_itn=True,
                ),
                tokens=str(Path(model_dir) / "tokens.txt"),
                provider=self._provider,
            ),
        )

        return sherpa_onnx.OfflineRecognizer(config)

    def _create_paraformer(self, sherpa_onnx) -> object:
        """创建 Paraformer 模型（中文专优）。"""

        model_dir = str(self._model_root / "paraformer")

        config = sherpa_onnx.OfflineRecognizerConfig(
            model=sherpa_onnx.OfflineModelConfig(
                paraformer=sherpa_onnx.OfflineParaformerModelConfig(
                    model=str(Path(model_dir) / "model.onnx"),
                ),
                tokens=str(Path(model_dir) / "tokens.txt"),
                provider=self._provider,
            ),
        )

        return sherpa_onnx.OfflineRecognizer(config)


# 常量引用，方便外部 import
ASR_SAMPLE_RATE = 16000
