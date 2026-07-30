"""OpenAI-compatible cloud audio adapters with bounded server-side transport."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import struct
import wave
from dataclasses import dataclass, field
from io import BytesIO
from urllib.parse import urlsplit

import httpx

from veyrasoul.orchestration.ports import (
    AsrUpdate,
    AsrUpdateHandler,
    SpeechSynthesisRequest,
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


@dataclass(frozen=True, slots=True)
class AudioAdapterCapabilities:
    tts_streaming: bool = False
    asr_streaming: bool = False
    cancellation_propagates: bool = True


@dataclass(frozen=True, slots=True)
class OpenAiAudioConfig:
    api_key: str = field(repr=False)
    base_url: str = "https://api.openai.com/v1"
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0
    max_response_bytes: int = 16 * 1024 * 1024
    max_connections: int = 20
    max_keepalive_connections: int = 10

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


class _OpenAiAudioTransport:
    def __init__(
        self,
        config: OpenAiAudioConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.client = httpx.AsyncClient(
            base_url=config.base_url + "/",
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "User-Agent": "Anima/0.0.1",
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

    async def aclose(self) -> None:
        await self.client.aclose()


class OpenAiCompatibleTts:
    capabilities = AudioAdapterCapabilities()

    def __init__(
        self,
        config: OpenAiAudioConfig,
        *,
        model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._transport = _OpenAiAudioTransport(config, transport=transport)
        self.model = _identifier(model, "TTS model")
        self.voice = _identifier(voice, "TTS voice")

    async def synthesize(self, request: SpeechSynthesisRequest) -> tuple[bytes, str]:
        text = request.text.strip()
        if not text or len(text) > 10_000:
            raise ValueError("TTS text must contain 1-10000 characters")
        voice = self.voice if request.voice_id == "default" else _identifier(
            request.voice_id, "TTS voice"
        )
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

    def create_session(self) -> "OpenAiCompatibleAsrSession":
        return OpenAiCompatibleAsrSession(self, self.endpoint_silence_ms)

    async def transcribe_pcm16(self, pcm16: bytes) -> str:
        if not pcm16 or len(pcm16) % 2:
            raise ValueError("PCM16 audio must contain complete samples")
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
        await self._transport.aclose()


class OpenAiCompatibleAsrSession:
    """PCM stream collector; upstream transcription itself is utterance-batch."""

    def __init__(self, adapter: OpenAiCompatibleAsr, silence_ms: int) -> None:
        self.adapter = adapter
        self.silence_bytes = 16_000 * 2 * silence_ms // 1_000
        self.handler: AsrUpdateHandler | None = None
        self.buffer = bytearray()
        self.trailing_silence = 0
        self.started = False
        self.closed = False
        self.tasks: set[asyncio.Task[None]] = set()

    async def start(self, handler: AsrUpdateHandler) -> None:
        if self.started:
            raise RuntimeError("ASR session already started")
        self.handler = handler
        self.started = True

    def submit_pcm16(self, pcm16: bytes) -> None:
        if not self.started or self.closed:
            raise RuntimeError("ASR session is not active")
        if not pcm16 or len(pcm16) % 2:
            raise ValueError("PCM16 frame is invalid")
        self.buffer.extend(pcm16)
        if _rms(pcm16) < 260:
            self.trailing_silence += len(pcm16)
        else:
            self.trailing_silence = 0
        if self.trailing_silence >= self.silence_bytes and len(self.buffer) > self.trailing_silence:
            utterance = bytes(self.buffer[:-self.trailing_silence])
            self.buffer.clear()
            self.trailing_silence = 0
            task = asyncio.create_task(self._transcribe(utterance))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def close(self) -> None:
        self.closed = True
        if self.buffer and len(self.buffer) > self.trailing_silence:
            await self._transcribe(bytes(self.buffer[:-self.trailing_silence or None]))
        self.buffer.clear()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)

    async def _transcribe(self, pcm16: bytes) -> None:
        text = await self.adapter.transcribe_pcm16(pcm16)
        if text and self.handler is not None:
            await self.handler(AsrUpdate(text, True))


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
    samples = struct.unpack(f"<{len(pcm16) // 2}h", pcm16)
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))
