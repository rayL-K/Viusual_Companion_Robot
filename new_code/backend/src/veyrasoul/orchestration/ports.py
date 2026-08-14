"""Runtime ports keep orchestration independent from concrete model engines."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol


class StreamingLlm(Protocol):
    def stream_reply(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...


@dataclass(frozen=True, slots=True)
class SpeechSynthesisRequest:
    text: str
    voice_id: str = "default"


@dataclass(frozen=True, slots=True)
class SpeechAudioFormat:
    """Explicit raw-audio contract for a streaming synthesis response."""

    content_type: str
    encoding: str
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int

    def __post_init__(self) -> None:
        if not self.content_type.strip() or not self.encoding.strip():
            raise ValueError("streaming audio format must name its content type and encoding")
        if not 8_000 <= self.sample_rate_hz <= 192_000:
            raise ValueError("streaming audio sample rate is out of range")
        if not 1 <= self.channels <= 8:
            raise ValueError("streaming audio channel count is out of range")
        if not 1 <= self.sample_width_bytes <= 4:
            raise ValueError("streaming audio sample width is out of range")


@dataclass(frozen=True, slots=True)
class SpeechSynthesisStream:
    """Pull-based chunks; closing the iterator must close the upstream response."""

    format: SpeechAudioFormat
    chunks: AsyncIterator[bytes]

    async def aclose(self) -> None:
        close = getattr(self.chunks, "aclose", None)
        if callable(close):
            await close()


@dataclass(frozen=True, slots=True)
class AudioAdapterCapabilities:
    """Provider-neutral media features used for runtime catalog negotiation."""

    tts_streaming: bool = False
    asr_streaming: bool = False
    cancellation_propagates: bool = True


class SpeechSynthesizer(Protocol):
    async def synthesize(self, request: SpeechSynthesisRequest) -> tuple[bytes, str]: ...


@dataclass(frozen=True, slots=True)
class AsrUpdate:
    text: str
    final: bool
    epoch: int = field(default=0, kw_only=True)


@dataclass(frozen=True, slots=True)
class AsrAdmissionFailure:
    """Stable, provider-neutral reason for refusing a paid ASR request."""

    code: str
    message: str


class AsrRequestLease(Protocol):
    async def release(self) -> None: ...


AsrUpdateHandler = Callable[[AsrUpdate], Awaitable[None]]
AsrAdmissionHandler = Callable[
    [],
    Awaitable[tuple[AsrRequestLease | None, AsrAdmissionFailure | None]],
]


class StreamingAsrSession(Protocol):
    @property
    def epoch(self) -> int: ...

    async def start(self, handler: AsrUpdateHandler) -> None: ...
    def submit_pcm16(self, pcm16: bytes) -> None: ...
    async def invalidate(self) -> None: ...
    async def close(self) -> None: ...


class StreamingAsrFactory(Protocol):
    def create_session(
        self,
        *,
        admit: AsrAdmissionHandler | None = None,
    ) -> StreamingAsrSession: ...
