"""语音活动检测 (VAD) + 语音打断。

基于 WebRTC VAD 的 3 状态机（IDLE → ACTIVE → INACTIVE），
检测到用户说话时广播 SPEECH_START 事件以触发 TTS 中断。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


VAD_SPEECH_START = "vad.speech_start"
VAD_SPEECH_END = "vad.speech_end"
VAD_SILENCE = "vad.silence"


class VADState(Enum):
    IDLE = auto()
    ACTIVE = auto()
    INACTIVE = auto()


@dataclass
class VADConfig:
    frame_ms: int = 30
    padding_ms: int = 300
    level: int = 2          # WebRTC 激进级别 (0-3)


class VoiceActivityDetector:
    """基于 WebRTC VAD 的语音活动检测器。

    不再依赖 PyTorch / Silero VAD，改用纯 C 扩展 webrtcvad。
    同样的 3 状态机逻辑，去掉 torch 后包体小 100x。

    Args:
        config: VAD 配置。
    """

    def __init__(self, config: Optional[VADConfig] = None) -> None:
        self._cfg = config or VADConfig()
        if self._cfg.frame_ms not in {10, 20, 30}:
            raise ValueError("WebRTC VAD frame_ms 只能是 10、20 或 30")
        if self._cfg.padding_ms <= 0:
            raise ValueError("VAD padding_ms 必须大于 0")
        if self._cfg.level not in {0, 1, 2, 3}:
            raise ValueError("WebRTC VAD level 必须在 0 到 3 之间")
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(self._cfg.level)
        except ImportError:
            logger.warning("webrtcvad 不可用，VAD 已禁用")
            self._vad = None
        self._state = VADState.IDLE
        self._silent_frames = 0
        self._sample_rate = 16000

    def process_chunk(self, audio_bytes: bytes) -> Iterator[str]:
        """处理一段音频数据，产生状态转移事件。

        Args:
            audio_bytes: int16 PCM 音频字节串，16000Hz 单声道。

        Yields:
            事件类型常量字符串。
        """

        if self._vad is None:
            return

        frames = self._split_frames(audio_bytes)
        is_speech_count = 0
        total_frames = 0

        for frame in frames:
            is_speech = self._vad.is_speech(frame, self._sample_rate)
            total_frames += 1
            if is_speech:
                is_speech_count += 1

        has_speech = is_speech_count > total_frames // 2 if total_frames > 0 else False

        event = self._transition(has_speech)
        if event:
            yield event

    def reset(self) -> None:
        self._state = VADState.IDLE
        self._silent_frames = 0

    def _split_frames(self, audio_bytes: bytes) -> list[bytes]:
        """将音频字节串按 frame_ms 切帧。"""

        frame_size = int(self._sample_rate * self._cfg.frame_ms / 1000) * 2
        frames = []
        for i in range(0, len(audio_bytes) - frame_size + 1, frame_size):
            frames.append(audio_bytes[i:i + frame_size])
        return frames

    def _transition(self, has_speech: bool) -> Optional[str]:
        if self._state == VADState.IDLE:
            if has_speech:
                self._state = VADState.ACTIVE
                self._silent_frames = 0
                logger.debug("VAD: IDLE → ACTIVE")
                return VAD_SPEECH_START

        elif self._state == VADState.ACTIVE:
            if not has_speech:
                self._state = VADState.INACTIVE
                self._silent_frames = 1

        elif self._state == VADState.INACTIVE:
            if has_speech:
                self._state = VADState.ACTIVE
                self._silent_frames = 0
            else:
                self._silent_frames += 1
                silent_ms = self._silent_frames * self._cfg.frame_ms
                if silent_ms >= self._cfg.padding_ms:
                    self._state = VADState.IDLE
                    self._silent_frames = 0
                    logger.debug("VAD: INACTIVE → IDLE")
                    return VAD_SPEECH_END

        return None
