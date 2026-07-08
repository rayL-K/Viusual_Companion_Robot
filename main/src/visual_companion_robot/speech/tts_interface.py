"""TTS（语音合成）抽象接口。

参考 Open-LLM-VTuber 设计：所有 TTS 后端返回**文件路径**而非 bytes，
由调用方负责读取和清理。基类提供异步包装和文件生命周期管理。

用法::

    from .tts_interface import create_tts_engine

    engine = create_tts_engine("sherpa", model_dir="main/models/tts/matcha-zh-baker")
    wav_path = engine.generate_audio("你好，我是草莓兔兔")
    # ... 播放 wav_path ...
    engine.cleanup(wav_path)
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------


class TTSInterface(ABC):
    """语音合成抽象基类。

    子类必须实现 ``generate_audio``。异步版本和文件清理由基类提供。
    """

    @abstractmethod
    def generate_audio(self, text: str, **kwargs) -> str:
        """合成语音并写入文件。

        Args:
            text: 待合成文本。
            **kwargs: 后端特定参数（语速、音色等）。

        Returns:
            WAV 文件的绝对路径。
        """
        ...

    async def async_generate_audio(self, text: str, **kwargs) -> str:
        """异步语音合成，默认在线程池中运行同步实现。"""

        return await asyncio.to_thread(self.generate_audio, text, **kwargs)

    def cleanup(self, file_path: str) -> None:
        """删除临时音频文件。"""

        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("清理音频文件失败：%s", file_path, exc_info=True)

    @staticmethod
    def temp_wav_path(prefix: str = "tts") -> str:
        """生成临时 WAV 文件路径。"""
        file_descriptor, path = tempfile.mkstemp(prefix=f"{prefix}_", suffix=".wav")
        os.close(file_descriptor)
        return path


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def create_tts_engine(engine_type: str, **kwargs) -> TTSInterface:
    """根据配置名称创建 TTS 引擎实例。

    Args:
        engine_type: 引擎名，当前支持 "sherpa" / "sherpa-onnx"。
        **kwargs: 传递给引擎构造函数的参数。

    Raises:
        ValueError: 不支持的引擎类型。
    """

    if engine_type in {"sherpa", "sherpa-onnx"}:
        from visual_companion_robot.voice.sherpa_tts import SherpaOnnxTTS, SherpaOnnxTTSAdapter

        return SherpaOnnxTTSAdapter(SherpaOnnxTTS(**kwargs))

    raise ValueError(f"不支持的 TTS 引擎类型：{engine_type}")
