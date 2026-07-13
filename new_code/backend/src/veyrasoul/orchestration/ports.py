"""Runtime ports keep orchestration independent from concrete model engines."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


class StreamingLlm(Protocol):
    def stream_reply(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...


@dataclass(frozen=True, slots=True)
class SpeechSynthesisRequest:
    text: str
    voice_id: str = "default"


class SpeechSynthesizer(Protocol):
    async def synthesize(self, request: SpeechSynthesisRequest) -> tuple[bytes, str]: ...


@dataclass(frozen=True, slots=True)
class AsrUpdate:
    text: str
    final: bool


AsrUpdateHandler = Callable[[AsrUpdate], Awaitable[None]]


class StreamingAsrSession(Protocol):
    async def start(self, handler: AsrUpdateHandler) -> None: ...
    def submit_pcm16(self, pcm16: bytes) -> None: ...
    async def close(self) -> None: ...


class StreamingAsrFactory(Protocol):
    def create_session(self) -> StreamingAsrSession: ...
