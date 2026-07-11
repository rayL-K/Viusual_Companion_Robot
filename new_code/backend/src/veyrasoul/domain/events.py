"""Typed event envelope shared by session orchestration modules."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class EventKind(str, Enum):
    AUDIO_FRAME = "audio.frame"
    SPEECH_STARTED = "speech.started"
    SPEECH_ENDED = "speech.ended"
    ASR_PARTIAL = "asr.partial"
    ASR_FINAL = "asr.final"
    VISUAL_SNAPSHOT = "perception.visual"
    USER_TEXT = "turn.user_text"
    TURN_CANCEL = "turn.cancel"
    REPLY_SEGMENT = "reply.segment"
    AVATAR_INTENT = "avatar.intent"


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    session_id: str
    turn_id: str
    generation: int
    sequence: int
    kind: EventKind
    payload: Mapping[str, Any] = field(default_factory=dict)
    sent_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    monotonic_ns: int = field(default_factory=time.monotonic_ns)

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if self.generation < 0 or self.sequence < 0:
            raise ValueError("generation and sequence must be non-negative")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_wire(self) -> dict[str, Any]:
        return {
            "v": 2,
            "type": self.kind.value,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "generation": self.generation,
            "seq": self.sequence,
            "sentAtMs": self.sent_at_ms,
            "payload": dict(self.payload),
        }
