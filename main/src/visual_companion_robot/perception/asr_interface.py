"""ASR（语音识别）抽象接口 + 后端工厂。

所有 ASR 后端只需实现 ``transcribe_np(audio: np.ndarray) -> str``，
异步版本由基类通过 ``asyncio.to_thread`` 自动提供。

用法::

    from .asr_interface import create_asr_engine

    engine = create_asr_engine("sherpa-onnx", model_type="paraformer", ...)
    text = engine.transcribe_np(audio_chunk)        # 同步
    text = await engine.async_transcribe_np(chunk)   # 异步
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# 所有 ASR 后端共用的音频格式常量
ASR_SAMPLE_RATE = 16000
ASR_NUM_CHANNELS = 1
ASR_SAMPLE_WIDTH = 2  # int16 = 2 bytes


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------


class ASRInterface(ABC):
    """语音识别抽象基类。

    子类只需实现 ``transcribe_np``，异步版本自动获得。
    """

    @abstractmethod
    def transcribe_np(self, audio: np.ndarray) -> str:
        """对 numpy 音频数组执行语音识别。

        Args:
            audio: float32 或 int16 的一维 numpy 数组，采样率 16000。

        Returns:
            识别出的文本字符串。
        """
        ...

    async def async_transcribe_np(self, audio: np.ndarray) -> str:
        """异步语音识别，默认在线程池中运行同步实现。

        子类如果本身支持异步（如 WebSocket API），可覆盖此方法。
        """

        return await asyncio.to_thread(self.transcribe_np, audio)


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def create_asr_engine(engine_type: str, **kwargs) -> ASRInterface:
    """根据配置名称创建 ASR 引擎实例。

    Args:
        engine_type: 引擎名，当前支持 "sherpa-onnx"。
        **kwargs: 传递给引擎构造函数的参数。

    Returns:
        ASRInterface 实例。

    Raises:
        ValueError: 不支持的引擎类型。
    """

    if engine_type == "sherpa-onnx":
        from .sherpa_onnx_asr import SherpaOnnxASR

        return SherpaOnnxASR(**kwargs)

    raise ValueError(f"不支持的 ASR 引擎类型：{engine_type}")
