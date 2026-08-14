"""OpenAI-compatible cloud audio adapters with bounded server-side transport."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import struct
import wave
import weakref
from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from io import BytesIO
from urllib.parse import urlsplit

import httpx

from veyrasoul import __version__
from veyrasoul.orchestration.ports import (
    AudioAdapterCapabilities,
    AsrAdmissionHandler,
    AsrUpdate,
    AsrUpdateHandler,
    SpeechAudioFormat,
    SpeechSynthesisRequest,
    SpeechSynthesisStream,
)


class CloudAudioError(RuntimeError):
    code = "cloud_audio_error"


class CloudAudioAuthenticationError(CloudAudioError):
    code = "authentication_failed"


class CloudAudioTimeoutError(CloudAudioError):
    code = "upstream_timeout"


class CloudAudioTransportError(CloudAudioError):
    code = "upstream_unavailable"


class CloudAudioResponseTooLargeError(CloudAudioError):
    code = "response_too_large"


class CloudAudioInvalidResponseError(CloudAudioError):
    code = "invalid_response"


class CloudAudioUpstreamError(CloudAudioError):
    code = "upstream_rejected"


class CloudAudioInputTooLargeError(CloudAudioError):
    code = "input_too_large"


@dataclass(frozen=True, slots=True)
class AsrSessionError:
    """Machine-readable ASR failure carried through the existing update callback."""

    code: str
    message: str
    details: Mapping[str, int | float | str]


@dataclass(frozen=True, slots=True)
class AsrErrorUpdate(AsrUpdate):
    """An ``AsrUpdate``-compatible error that never becomes user transcript text."""

    error: AsrSessionError


@dataclass(frozen=True, slots=True)
class OpenAiAudioConfig:
    api_key: str = field(repr=False)
    base_url: str = "https://api.openai.com/v1"
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0
    max_response_bytes: int = 16 * 1024 * 1024
    max_connections: int = 20
    max_keepalive_connections: int = 10
    tts_stream_chunk_bytes: int = 4_096
    tts_streaming_enabled: bool = False
    asr_max_utterance_seconds: float = 30.0
    asr_max_utterance_bytes: int = 1_048_576
    asr_max_pending_utterances: int = 2

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OpenAI-compatible audio API key is required")
        object.__setattr__(self, "base_url", _validated_base_url(self.base_url))
        for name, value in (
            ("connect_timeout_seconds", self.connect_timeout_seconds),
            ("read_timeout_seconds", self.read_timeout_seconds),
        ):
            if not math.isfinite(value) or not 0.1 <= value <= 120:
                raise ValueError(f"{name} must be between 0.1 and 120")
        if not 1_024 <= self.max_response_bytes <= 128 * 1024 * 1024:
            raise ValueError("max_response_bytes is out of range")
        if not 1 <= self.max_connections <= 1_000:
            raise ValueError("max_connections is out of range")
        if not 0 <= self.max_keepalive_connections <= self.max_connections:
            raise ValueError("max_keepalive_connections is out of range")
        if (
            not 512 <= self.tts_stream_chunk_bytes <= 64 * 1024
            or self.tts_stream_chunk_bytes % 2
        ):
            raise ValueError("tts_stream_chunk_bytes must be an even value between 512 and 65536")
        if (
            not math.isfinite(self.asr_max_utterance_seconds)
            or not 0.25 <= self.asr_max_utterance_seconds <= 300
        ):
            raise ValueError("asr_max_utterance_seconds must be between 0.25 and 300")
        if (
            not 1_024 <= self.asr_max_utterance_bytes <= 16 * 1024 * 1024
            or self.asr_max_utterance_bytes % 2
        ):
            raise ValueError(
                "asr_max_utterance_bytes must be an even value between 1024 and 16777216"
            )
        if not 1 <= self.asr_max_pending_utterances <= 8:
            raise ValueError("asr_max_pending_utterances must be between 1 and 8")


class _OpenAiAudioTransport:
    def __init__(
        self,
        config: OpenAiAudioConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.http2_enabled = transport is None
        self.client = httpx.AsyncClient(
            base_url=config.base_url + "/",
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "User-Agent": f"Anima/{__version__}",
            },
            timeout=httpx.Timeout(
                connect=config.connect_timeout_seconds,
                read=config.read_timeout_seconds,
                write=config.read_timeout_seconds,
                pool=config.connect_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_keepalive_connections,
            ),
            follow_redirects=False,
            transport=transport,
            http2=self.http2_enabled,
        )

    async def request(
        self, method: str, path: str, **kwargs: object
    ) -> tuple[bytes, str]:
        try:
            async with self.client.stream(method, path, **kwargs) as response:
                if response.status_code in {401, 403}:
                    raise CloudAudioAuthenticationError("云语音认证失败")
                if not 200 <= response.status_code < 300:
                    raise CloudAudioUpstreamError(
                        f"云语音服务拒绝请求（HTTP {response.status_code}）"
                    )
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(payload) + len(chunk) > self.config.max_response_bytes:
                        raise CloudAudioResponseTooLargeError("云语音响应超过大小限制")
                    payload.extend(chunk)
                return bytes(payload), response.headers.get("content-type", "")
        except asyncio.CancelledError:
            raise
        except CloudAudioError:
            raise
        except httpx.TimeoutException as exc:
            raise CloudAudioTimeoutError("云语音请求超时") from exc
        except httpx.HTTPError as exc:
            raise CloudAudioTransportError("云语音服务暂时不可达") from exc

    async def stream(
        self,
        method: str,
        path: str,
        *,
        chunk_size: int,
        accepted_content_types: frozenset[str],
        **kwargs: object,
    ) -> AsyncIterator[bytes]:
        """Yield one bounded upstream chunk at a time and close on cancellation."""

        try:
            async with self.client.stream(method, path, **kwargs) as response:
                if response.status_code in {401, 403}:
                    raise CloudAudioAuthenticationError("云语音认证失败")
                if not 200 <= response.status_code < 300:
                    raise CloudAudioUpstreamError(
                        f"云语音服务拒绝请求（HTTP {response.status_code}）"
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                content_type = content_type.strip().lower()
                if content_type and content_type not in accepted_content_types:
                    raise CloudAudioInvalidResponseError(
                        f"云语音返回了不支持的流格式 {content_type}"
                    )
                total_bytes = 0
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > self.config.max_response_bytes:
                        raise CloudAudioResponseTooLargeError("云语音响应超过大小限制")
                    for offset in range(0, len(chunk), chunk_size):
                        yield chunk[offset : offset + chunk_size]
        except asyncio.CancelledError:
            # Exiting AsyncClient.stream closes the response/socket before cancellation
            # reaches the caller, so a superseded turn stops consuming provider capacity.
            raise
        except CloudAudioError:
            raise
        except httpx.TimeoutException as exc:
            raise CloudAudioTimeoutError("云语音请求超时") from exc
        except httpx.HTTPError as exc:
            raise CloudAudioTransportError("云语音服务暂时不可达") from exc

    async def aclose(self) -> None:
        await self.client.aclose()


class OpenAiCompatibleTts:
    streaming_format = SpeechAudioFormat(
        content_type="audio/pcm",
        encoding="pcm_s16le",
        sample_rate_hz=24_000,
        channels=1,
        sample_width_bytes=2,
    )

    def __init__(
        self,
        config: OpenAiAudioConfig,
        *,
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._transport = _OpenAiAudioTransport(config, transport=transport)
        self.capabilities = AudioAdapterCapabilities(
            tts_streaming=config.tts_streaming_enabled
        )
        self.model = _identifier(model, "TTS model")
        self.voice = _identifier(voice, "TTS voice")

    async def synthesize(self, request: SpeechSynthesisRequest) -> tuple[bytes, str]:
        text, voice = self._validated_request(request)
        payload, content_type = await self._transport.request(
            "POST",
            "audio/speech",
            json={
                "model": self.model,
                "input": text,
                "voice": voice,
                "response_format": "wav",
            },
            headers={"Accept": "audio/wav"},
        )
        if len(payload) < 12 or payload[:4] != b"RIFF":
            raise CloudAudioInvalidResponseError("云 TTS 未返回有效 WAV")
        return payload, content_type.split(";", 1)[0] or "audio/wav"

    async def stream_synthesize(
        self,
        request: SpeechSynthesisRequest,
    ) -> SpeechSynthesisStream:
        """Use OpenAI's raw 24 kHz PCM stream without buffering the response."""

        if not self.capabilities.tts_streaming:
            raise RuntimeError(
                "streaming TTS is disabled for this OpenAI-compatible binding"
            )
        text, voice = self._validated_request(request)

        async def chunks() -> AsyncIterator[bytes]:
            trailing_byte = b""
            async for chunk in self._transport.stream(
                "POST",
                "audio/speech",
                chunk_size=self._transport.config.tts_stream_chunk_bytes,
                accepted_content_types=frozenset({"audio/pcm", "application/octet-stream"}),
                json={
                    "model": self.model,
                    "input": text,
                    "voice": voice,
                    "response_format": "pcm",
                    "stream_format": "audio",
                },
                headers={"Accept": "audio/pcm, application/octet-stream"},
            ):
                payload = trailing_byte + chunk
                aligned_bytes = len(payload) - (
                    len(payload) % self.streaming_format.sample_width_bytes
                )
                if aligned_bytes:
                    yield payload[:aligned_bytes]
                trailing_byte = payload[aligned_bytes:]
            if trailing_byte:
                raise CloudAudioInvalidResponseError("云 TTS PCM 响应包含不完整采样")

        return SpeechSynthesisStream(self.streaming_format, chunks())

    def _validated_request(self, request: SpeechSynthesisRequest) -> tuple[str, str]:
        text = request.text.strip()
        if not text or len(text) > 10_000:
            raise ValueError("TTS text must contain 1-10000 characters")
        voice = self.voice if request.voice_id == "default" else _identifier(
            request.voice_id, "TTS voice"
        )
        return text, voice

    async def warmup(self) -> None:
        return

    async def aclose(self) -> None:
        await self._transport.aclose()


class OpenAiCompatibleAsr:
    capabilities = AudioAdapterCapabilities()

    def __init__(
        self,
        config: OpenAiAudioConfig,
        *,
        model: str = "gpt-4o-mini-transcribe",
        transport: httpx.AsyncBaseTransport | None = None,
        endpoint_silence_ms: int = 600,
    ) -> None:
        self._transport = _OpenAiAudioTransport(config, transport=transport)
        self.model = _identifier(model, "ASR model")
        if not 200 <= endpoint_silence_ms <= 3_000:
            raise ValueError("endpoint_silence_ms must be between 200 and 3000")
        self.endpoint_silence_ms = endpoint_silence_ms
        duration_bytes = int(config.asr_max_utterance_seconds * 16_000 * 2)
        self.max_utterance_bytes = min(
            config.asr_max_utterance_bytes,
            duration_bytes - (duration_bytes % 2),
        )
        self.max_pending_utterances = config.asr_max_pending_utterances
        self._sessions: weakref.WeakSet[OpenAiCompatibleAsrSession] = weakref.WeakSet()

    def create_session(
        self,
        *,
        admit: AsrAdmissionHandler | None = None,
    ) -> "OpenAiCompatibleAsrSession":
        session = OpenAiCompatibleAsrSession(
            self,
            self.endpoint_silence_ms,
            max_utterance_bytes=self.max_utterance_bytes,
            max_pending_utterances=self.max_pending_utterances,
            admit=admit,
        )
        self._sessions.add(session)
        return session

    async def transcribe_pcm16(self, pcm16: bytes) -> str:
        if not pcm16 or len(pcm16) % 2:
            raise ValueError("PCM16 audio must contain complete samples")
        if len(pcm16) > self.max_utterance_bytes:
            raise CloudAudioInputTooLargeError(
                f"PCM16 utterance exceeds {self.max_utterance_bytes} bytes"
            )
        wav = _pcm16_wav(pcm16)
        payload, _ = await self._transport.request(
            "POST",
            "audio/transcriptions",
            data={"model": self.model, "response_format": "json"},
            files={"file": ("speech.wav", wav, "audio/wav")},
            headers={"Accept": "application/json"},
        )
        try:
            value = json.loads(payload)
            text = value.get("text") if isinstance(value, dict) else None
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CloudAudioInvalidResponseError("云 ASR 响应不是有效 JSON") from exc
        if not isinstance(text, str):
            raise CloudAudioInvalidResponseError("云 ASR 响应缺少 text")
        return text.strip()

    async def warmup(self) -> None:
        return

    async def aclose(self) -> None:
        sessions = tuple(self._sessions)
        if sessions:
            await asyncio.gather(
                *(session.close() for session in sessions),
                return_exceptions=True,
            )
        await self._transport.aclose()


class OpenAiCompatibleAsrSession:
    """Bounded PCM collector with one ordered upstream transcription worker."""

    def __init__(
        self,
        adapter: OpenAiCompatibleAsr,
        silence_ms: int,
        *,
        max_utterance_bytes: int,
        max_pending_utterances: int,
        admit: AsrAdmissionHandler | None = None,
    ) -> None:
        self.adapter = adapter
        self.silence_bytes = 16_000 * 2 * silence_ms // 1_000
        self.max_utterance_bytes = max_utterance_bytes
        self.max_pending_utterances = max_pending_utterances
        self.handler: AsrUpdateHandler | None = None
        self.buffer = bytearray()
        self.trailing_silence = 0
        self.started = False
        self.closed = False
        self._discarding_oversized = False
        self._sequence = 0
        self._queued_utterances = 0
        self._items: deque[_QueuedAsrUtterance | _QueuedAsrError] = deque()
        self._pending_errors: dict[str, _QueuedAsrError] = {}
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._admit = admit
        self._epoch = 0
        self._inflight: asyncio.Task[str] | None = None
        self._inflight_epoch: int | None = None
        self._emit_task: asyncio.Task[None] | None = None

    @property
    def epoch(self) -> int:
        return self._epoch

    async def start(self, handler: AsrUpdateHandler) -> None:
        if self.started:
            raise RuntimeError("ASR session already started")
        if self.closed:
            raise RuntimeError("ASR session is closed")
        self.handler = handler
        self.started = True
        self._worker = asyncio.create_task(
            self._run(),
            name="openai-compatible-asr",
        )

    def submit_pcm16(self, pcm16: bytes) -> None:
        worker = self._worker
        if not self.started or self.closed or worker is None or worker.done():
            raise RuntimeError("ASR session is not active")
        if not pcm16 or len(pcm16) % 2:
            raise ValueError("PCM16 frame is invalid")

        silent = _rms(pcm16) < 260
        if self._discarding_oversized:
            if silent:
                self.trailing_silence = min(
                    self.silence_bytes,
                    self.trailing_silence + len(pcm16),
                )
                if self.trailing_silence >= self.silence_bytes:
                    self._discarding_oversized = False
                    self.trailing_silence = 0
            else:
                self.trailing_silence = 0
            return

        if silent:
            self.trailing_silence = min(
                self.silence_bytes,
                self.trailing_silence + len(pcm16),
            )
            if self.trailing_silence >= self.silence_bytes:
                if self.buffer:
                    self._enqueue_utterance(bytes(self.buffer))
                self.buffer.clear()
                self.trailing_silence = 0
            return

        observed_bytes = len(self.buffer) + self.trailing_silence + len(pcm16)
        if observed_bytes > self.max_utterance_bytes:
            sequence = self._next_sequence()
            self.buffer.clear()
            self.trailing_silence = 0
            self._discarding_oversized = True
            self._enqueue_error(
                sequence,
                code="asr_utterance_too_large",
                message="语音单句超过服务端限制，已丢弃到下一个静音端点",
                details={
                    "observedBytes": observed_bytes,
                    "maxBytes": self.max_utterance_bytes,
                },
            )
            return

        if self.trailing_silence:
            self.buffer.extend(b"\0" * self.trailing_silence)
        self.buffer.extend(pcm16)
        self.trailing_silence = 0

    async def invalidate(self) -> None:
        """Start a fresh capture epoch and promptly abandon stale cloud work."""

        self._epoch += 1
        self.buffer.clear()
        self.trailing_silence = 0
        self._discarding_oversized = False
        self._items.clear()
        self._queued_utterances = 0
        self._pending_errors.clear()
        self._wake.clear()
        inflight = self._inflight
        if inflight is not None and not inflight.done():
            inflight.cancel()
        emit_task = self._emit_task
        if emit_task is not None and not emit_task.done():
            emit_task.cancel()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.invalidate()
        self.handler = None
        self._wake.set()
        worker = self._worker
        self._worker = None
        if worker is not None and not worker.done():
            worker.cancel()
        if worker is not None and worker is not asyncio.current_task():
            await asyncio.gather(worker, return_exceptions=True)

    def _next_sequence(self) -> int:
        sequence = self._sequence
        self._sequence += 1
        return sequence

    def _enqueue_utterance(self, pcm16: bytes) -> None:
        sequence = self._next_sequence()
        if self._queued_utterances >= self.max_pending_utterances:
            self._enqueue_error(
                sequence,
                code="asr_queue_full",
                message="云端语音识别队列已满，本句已丢弃",
                details={"maxPendingUtterances": self.max_pending_utterances},
            )
            return
        self._items.append(_QueuedAsrUtterance(sequence, pcm16, self._epoch))
        self._queued_utterances += 1
        self._wake.set()

    def _enqueue_error(
        self,
        sequence: int,
        *,
        code: str,
        message: str,
        details: Mapping[str, int | float | str],
    ) -> None:
        pending = self._pending_errors.get(code)
        if pending is not None:
            pending.occurrences += 1
            pending.last_sequence = sequence
            return
        item = _QueuedAsrError(
            sequence=sequence,
            last_sequence=sequence,
            code=code,
            message=message,
            details=dict(details),
            epoch=self._epoch,
        )
        self._pending_errors[code] = item
        self._items.append(item)
        self._wake.set()

    async def _run(self) -> None:
        while True:
            await self._wake.wait()
            while self._items:
                item = self._items.popleft()
                if isinstance(item, _QueuedAsrUtterance):
                    self._queued_utterances -= 1
                    await self._transcribe(item)
                else:
                    self._pending_errors.pop(item.code, None)
                    await self._emit_error(item)
                if self.closed:
                    return
            self._wake.clear()
            if self._items:
                self._wake.set()

    async def _transcribe(self, item: "_QueuedAsrUtterance") -> None:
        if item.epoch != self._epoch:
            return
        lease = None
        try:
            if self._admit is not None:
                lease, failure = await self._admit()
                if item.epoch != self._epoch:
                    return
                if lease is None:
                    await self._emit(
                        AsrErrorUpdate(
                            text="",
                            final=False,
                            epoch=item.epoch,
                            error=AsrSessionError(
                                code=(failure.code if failure else "server_busy"),
                                message=(
                                    failure.message
                                    if failure
                                    else "语音识别服务繁忙，请稍后再试"
                                ),
                                details={"sequence": item.sequence},
                            ),
                        ),
                        item.epoch,
                    )
                    return
            if item.epoch != self._epoch:
                return
            operation = asyncio.create_task(
                self.adapter.transcribe_pcm16(item.pcm16),
                name=f"openai-compatible-asr-http:{item.sequence}",
            )
            self._inflight = operation
            self._inflight_epoch = item.epoch
            text = await operation
        except asyncio.CancelledError:
            if self.closed or item.epoch != self._epoch:
                return
            raise
        except Exception as exc:
            if item.epoch != self._epoch:
                return
            code = exc.code if isinstance(exc, CloudAudioError) else "asr_transcription_failed"
            await self._emit(
                AsrErrorUpdate(
                    text="",
                    final=False,
                    epoch=item.epoch,
                    error=AsrSessionError(
                        code=code,
                        message=str(exc) or "云端语音识别失败",
                        details={"sequence": item.sequence},
                    ),
                ),
                item.epoch,
            )
            return
        finally:
            if self._inflight_epoch == item.epoch:
                self._inflight = None
                self._inflight_epoch = None
            if lease is not None:
                await _release_lease_uninterruptibly(lease)
        if item.epoch != self._epoch:
            return
        if text:
            await self._emit(AsrUpdate(text, True, epoch=item.epoch), item.epoch)

    async def _emit_error(self, item: "_QueuedAsrError") -> None:
        if item.epoch != self._epoch:
            return
        details = dict(item.details)
        details.update(
            {
                "sequence": item.sequence,
                "lastSequence": item.last_sequence,
                "occurrences": item.occurrences,
            }
        )
        await self._emit(
            AsrErrorUpdate(
                text="",
                final=False,
                epoch=item.epoch,
                error=AsrSessionError(item.code, item.message, details),
            ),
            item.epoch,
        )

    async def _emit(self, update: AsrUpdate, epoch: int) -> None:
        handler = self.handler
        if self.closed or handler is None or epoch != self._epoch:
            return
        task = asyncio.create_task(handler(update), name="openai-compatible-asr-emit")
        self._emit_task = task
        try:
            await task
        except asyncio.CancelledError:
            if self.closed or epoch != self._epoch:
                return
            raise
        except Exception:
            # A consumer callback must not permanently kill the one bounded worker.
            return
        finally:
            if self._emit_task is task:
                self._emit_task = None


@dataclass(frozen=True, slots=True)
class _QueuedAsrUtterance:
    sequence: int
    pcm16: bytes
    epoch: int


@dataclass(slots=True)
class _QueuedAsrError:
    sequence: int
    last_sequence: int
    code: str
    message: str
    details: dict[str, int | float | str]
    epoch: int
    occurrences: int = 1


async def _release_lease_uninterruptibly(lease) -> None:
    """Never strand global ASR concurrency when the session is cancelled."""

    release = asyncio.create_task(lease.release(), name="release-asr-admission")
    try:
        await asyncio.shield(release)
    except asyncio.CancelledError:
        while not release.done():
            try:
                await asyncio.shield(release)
            except asyncio.CancelledError:
                continue
        raise


def _validated_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("audio base_url must not contain credentials, query, or fragment")
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("audio base_url must be an absolute HTTP(S) URL")
    loopback = parsed.hostname.lower() == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme != "https" and not loopback:
        raise ValueError("audio base_url requires HTTPS except for loopback")
    return value.strip().rstrip("/")


def _identifier(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 200 or any(char.isspace() for char in normalized):
        raise ValueError(f"{label} is invalid")
    return normalized


def _pcm16_wav(pcm16: bytes) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(pcm16)
    return output.getvalue()


def _rms(pcm16: bytes) -> float:
    sample_count = len(pcm16) // 2
    energy = sum(
        sample[0] * sample[0]
        for sample in struct.iter_unpack("<h", pcm16)
    )
    return math.sqrt(energy / sample_count)
