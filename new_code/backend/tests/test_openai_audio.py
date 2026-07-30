from __future__ import annotations

import asyncio
import json
import wave
from io import BytesIO

import httpx
import pytest

from veyrasoul.integrations.openai_audio import (
    CloudAudioAuthenticationError,
    CloudAudioResponseTooLargeError,
    CloudAudioTimeoutError,
    OpenAiAudioConfig,
    OpenAiCompatibleAsr,
    OpenAiCompatibleTts,
)
from veyrasoul.orchestration.ports import SpeechSynthesisRequest


def async_test(function):
    def run() -> None:
        asyncio.run(function())

    return run


def _wav() -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\0\0" * 160)
    return output.getvalue()


@pytest.mark.parametrize(
    "url",
    ["http://audio.example/v1", "https://u:p@audio.example/v1", "relative/v1"],
)
def test_config_rejects_unsafe_upstream_urls(url: str) -> None:
    with pytest.raises(ValueError):
        OpenAiAudioConfig(api_key="secret", base_url=url)


@async_test
async def test_tts_uses_server_auth_and_returns_wav() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer server-secret"
        assert json.loads(request.content)["input"] == "你好"
        return httpx.Response(200, content=_wav(), headers={"content-type": "audio/wav"})

    adapter = OpenAiCompatibleTts(
        OpenAiAudioConfig(api_key="server-secret", base_url="https://audio.example/v1"),
        transport=httpx.MockTransport(handler),
    )
    try:
        payload, content_type = await adapter.synthesize(SpeechSynthesisRequest("你好"))
        assert payload.startswith(b"RIFF") and content_type == "audio/wav"
        assert adapter.capabilities.cancellation_propagates
        assert not adapter.capabilities.tts_streaming
    finally:
        await adapter.aclose()


@async_test
async def test_asr_posts_wav_and_parses_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/audio/transcriptions")
        assert b"speech.wav" in request.content
        return httpx.Response(200, json={"text": " hello "})

    adapter = OpenAiCompatibleAsr(
        OpenAiAudioConfig(api_key="secret"),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await adapter.transcribe_pcm16(b"\1\0" * 160) == "hello"
    finally:
        await adapter.aclose()


@async_test
async def test_stable_auth_timeout_and_size_errors() -> None:
    async def unauthorized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    adapter = OpenAiCompatibleTts(
        OpenAiAudioConfig(api_key="secret"), transport=httpx.MockTransport(unauthorized)
    )
    with pytest.raises(CloudAudioAuthenticationError):
        await adapter.synthesize(SpeechSynthesisRequest("hello"))
    await adapter.aclose()

    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("late", request=request)

    adapter = OpenAiCompatibleTts(
        OpenAiAudioConfig(api_key="secret"), transport=httpx.MockTransport(timeout)
    )
    with pytest.raises(CloudAudioTimeoutError):
        await adapter.synthesize(SpeechSynthesisRequest("hello"))
    await adapter.aclose()

    async def oversized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"R" * 1025)

    adapter = OpenAiCompatibleTts(
        OpenAiAudioConfig(api_key="secret", max_response_bytes=1024),
        transport=httpx.MockTransport(oversized),
    )
    with pytest.raises(CloudAudioResponseTooLargeError):
        await adapter.synthesize(SpeechSynthesisRequest("hello"))
    await adapter.aclose()


@async_test
async def test_cancellation_propagates() -> None:
    started = asyncio.Event()

    async def blocked(_: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(60)
        return httpx.Response(200, content=_wav())

    adapter = OpenAiCompatibleTts(
        OpenAiAudioConfig(api_key="secret"), transport=httpx.MockTransport(blocked)
    )
    task = asyncio.create_task(adapter.synthesize(SpeechSynthesisRequest("hello")))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await adapter.aclose()
