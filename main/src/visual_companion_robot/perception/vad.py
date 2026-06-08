"""语音活动检测 (VAD) + 语音打断。

基于 Silero VAD 的 3 状态机（IDLE → ACTIVE → INACTIVE），参考
Open-LLM-VTuber 的参数设计。检测到用户说话时通过 RuntimeBus 广播
``SPEECH_START`` 事件以触发 TTS 中断。

用法::

    vad = VoiceActivityDetector()
    for event in vad.process_chunk(audio_bytes):
        bus.emit(RobotEvent(event_type=event, source="vad", payload={}))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


# ---- 事件常量 ----
VAD_SPEECH_START = "vad.speech_start"
"""用户开始说话，应中断当前 TTS 播放。"""
VAD_SPEECH_END = "vad.speech_end"
"""用户说完话，可以提交 ASR 转录。"""
VAD_SILENCE = "vad.silence"
"""长时间静音。"""


class VADState(Enum):
    IDLE = auto()       # 静音中，等待语音
    ACTIVE = auto()     # 检测到语音，持续收集中
    INACTIVE = auto()   # 语音刚结束，等待确认静音


@dataclass
class VADConfig:
    """VAD 灵敏度配置，参考 Open-LLM-VTuber 参数设计。"""

    prob_threshold: float = 0.4
    """Silero VAD 概率阈值，超过此值视为语音。"""

    db_threshold: float = 60.0
    """RMS 分贝阈值，低于此值的微弱信号忽略。"""

    required_hits: int = 3
    """连续多少帧超过阈值才确认进入 ACTIVE（~0.1s @ 30ms/帧）。"""

    required_misses: int = 24
    """连续多少帧低于阈值才确认回到 IDLE（~0.8s @ 30ms/帧）。"""

    smoothing_window: int = 5
    """滑动平均窗口，用于平滑概率和分贝值。"""

    frame_ms: int = 30
    """每帧时长（毫秒），Silero VAD 固定为 30ms。"""


class VoiceActivityDetector:
    """基于 Silero VAD 的语音活动检测器。

    Args:
        config: VAD 灵敏度配置，默认使用 VADConfig()。
    """

    def __init__(self, config: Optional[VADConfig] = None) -> None:
        self._cfg = config or VADConfig()
        self._state = VADState.IDLE
        self._hit_count = 0
        self._miss_count = 0
        self._prob_history = []   # type: list[float]
        self._db_history = []     # type: list[float]
        self._model = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def process_chunk(self, audio_bytes: bytes) -> Iterator[str]:
        """处理一段音频数据，产生状态转移事件。

        Args:
            audio_bytes: int16 PCM 音频字节串，16000Hz 单声道。

        Yields:
            事件类型常量字符串。
        """

        import numpy as np

        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        prob = self._predict(samples)

        # RMS 分贝
        rms = np.sqrt(np.mean(samples ** 2)) if len(samples) > 0 else 0.0
        db = 20 * np.log10(rms + 1e-10)

        # 滑动平均
        self._prob_history.append(prob)
        self._db_history.append(db)
        if len(self._prob_history) > self._cfg.smoothing_window:
            self._prob_history.pop(0)
            self._db_history.pop(0)

        smooth_prob = sum(self._prob_history) / len(self._prob_history)
        smooth_db = sum(self._db_history) / len(self._db_history)

        # 语音判断
        has_speech = smooth_prob >= self._cfg.prob_threshold and smooth_db >= self._cfg.db_threshold

        if has_speech:
            self._hit_count += 1
            self._miss_count = 0
        else:
            self._miss_count += 1

        # 状态转移
        event = self._transition(has_speech)
        if event:
            yield event

    def reset(self) -> None:
        """重置状态机，取消进行中的语音检测。"""

        self._state = VADState.IDLE
        self._hit_count = 0
        self._miss_count = 0
        self._prob_history.clear()
        self._db_history.clear()

    # ------------------------------------------------------------------
    # 内部：Silero VAD 推理
    # ------------------------------------------------------------------

    def _predict(self, samples) -> float:
        """单帧 Silero VAD 概率预测。"""

        import torch

        if self._model is None:
            self._load_model()

        tensor = torch.from_numpy(samples.copy())
        return self._model(tensor, 16000).item()

    def _load_model(self) -> None:
        """懒加载 Silero VAD 模型。"""

        import torch

        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
            verbose=False,
        )
        self._model = model

    # ------------------------------------------------------------------
    # 内部：状态机
    # ------------------------------------------------------------------

    def _transition(self, has_speech: bool) -> Optional[str]:
        """执行状态转移，返回触发的事件名。"""

        if self._state == VADState.IDLE:
            if self._hit_count >= self._cfg.required_hits:
                self._state = VADState.ACTIVE
                logger.debug("VAD: IDLE → ACTIVE（检测到语音）")
                return VAD_SPEECH_START

        elif self._state == VADState.ACTIVE:
            if not has_speech and self._miss_count >= 1:
                self._state = VADState.INACTIVE

        elif self._state == VADState.INACTIVE:
            if has_speech:
                self._state = VADState.ACTIVE
                self._miss_count = 0
            elif self._miss_count >= self._cfg.required_misses:
                self._state = VADState.IDLE
                self._hit_count = 0
                self._miss_count = 0
                logger.debug("VAD: INACTIVE → IDLE（语音结束）")
                return VAD_SPEECH_END

        return None
