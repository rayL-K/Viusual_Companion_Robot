from __future__ import annotations

import asyncio
import json
import wave
from io import BytesIO
from unittest.mock import patch

import httpx
import pytest

from veyrasoul.integrations.openai_audio import (
    AsrErrorUpdate,
    CloudAudioAuthenticationError,
    CloudAudioInputTooLargeError,
    CloudAudioInvalidResponseError,
    CloudAudioResponseTooLargeError,
    CloudAudioTimeoutError,
    OpenAiAudioConfig,
    OpenAiCompatibleAsr,
    OpenAiCompatibleTts,
)
from veyrasoul.orchestration.ports import AsrAdmissionFailure, SpeechSynthesisRequest


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


def _submit_utterance(session, sample: int) -> None:
    session.submit_pcm16((sample * 1_000).to_bytes(2, "little", signed=True) * 320)
    session.submit_pcm16(b"\0\0" * 3_200)


class ControlledPcmStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.release_second = asyncio.Event()
        self.waiting_for_second = asyncio.Event()
        self.closed = asyncio.Event()

    async def __aiter__(self):
        yield b"\x01\x00\x02"
        self.waiting_for_second.set()
        await self.release_second.wait()
        yield b"\x00\x03\x00"

    async def aclose(self) -> None:
        self.closed.set()


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
async def test_streaming_tts_yields_aligned_pcm_before_upstream_finishes() -> None:
    upstream = ControlledPcmStream()

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == "pcm"
        assert body["stream_format"] == "audio"
        return httpx.Response(
            200,
            stream=upstream,
            headers={"content-type": "audio/pcm"},
        )

    adapter = OpenAiCompatibleTts(
        OpenAiAudioConfig(api_key="secret", tts_streaming_enabled=True),
        transport=httpx.MockTransport(handler),
    )
    stream = await adapter.stream_synthesize(SpeechSynthesisRequest("hello"))
    iterator = stream.chunks.__aiter__()
    try:
        first = await asyncio.wait_for(anext(iterator), 1)
        assert first == b"\x01\x00"
        assert stream.format.encoding == "pcm_s16le"
        assert stream.format.sample_rate_hz == 24_000
        assert not upstream.release_second.is_set()
        upstream.release_second.set()
        assert await asyncio.wait_for(anext(iterator), 1) == b"\x02\x00\x03\x00"
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
        assert upstream.closed.is_set()
    finally:
        await stream.aclose()
        await adapter.aclose()


@async_test
async def test_compatible_binding_does_not_assume_streaming_support() -> None:
    called = False

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(400)

    adapter = OpenAiCompatibleTts(
        OpenAiAudioConfig(api_key="secret"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="disabled"):
        await adapter.stream_synthesize(SpeechSynthesisRequest("hello"))
    assert called is False
    await adapter.aclose()


@async_test
async def test_streaming_tts_cancellation_closes_upstream_response_immediately() -> None:
    upstream = ControlledPcmStream()

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=upstream,
            headers={"content-type": "application/octet-stream"},
        )

    adapter = OpenAiCompatibleTts(
        OpenAiAudioConfig(api_key="secret", tts_streaming_enabled=True),
        transport=httpx.MockTransport(handler),
    )
    stream = await adapter.stream_synthesize(SpeechSynthesisRequest("hello"))
    iterator = stream.chunks.__aiter__()
    assert await anext(iterator) == b"\x01\x00"
    pending = asyncio.create_task(anext(iterator))
    await upstream.waiting_for_second.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert upstream.closed.is_set()
    await adapter.aclose()


@async_test
async def test_streaming_tts_rejects_truncated_pcm_sample() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"\x01",
            headers={"content-type": "audio/pcm"},
        )

    adapter = OpenAiCompatibleTts(
        OpenAiAudioConfig(api_key="secret", tts_streaming_enabled=True),
        transport=httpx.MockTransport(handler),
    )
    stream = await adapter.stream_synthesize(SpeechSynthesisRequest("hello"))
    with pytest.raises(CloudAudioInvalidResponseError):
        async for _ in stream.chunks:
            pass
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


def test_default_transport_enables_http2_but_mock_transport_does_not() -> None:
    clients = []

    class RecordingClient:
        def __init__(self, **kwargs) -> None:
            clients.append(kwargs)

    with patch("veyrasoul.integrations.openai_audio.httpx.AsyncClient", RecordingClient):
        OpenAiCompatibleTts(OpenAiAudioConfig(api_key="secret"))
        OpenAiCompatibleTts(
            OpenAiAudioConfig(api_key="secret"),
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=_wav())),
        )
    assert [client["http2"] for client in clients] == [True, False]


def test_asr_config_rejects_unsafe_resource_bounds() -> None:
    with pytest.raises(ValueError, match="asr_max_utterance_seconds"):
        OpenAiAudioConfig(api_key="secret", asr_max_utterance_seconds=float("inf"))
    with pytest.raises(ValueError, match="asr_max_utterance_bytes"):
        OpenAiAudioConfig(api_key="secret", asr_max_utterance_bytes=1_023)
    with pytest.raises(ValueError, match="asr_max_pending_utterances"):
        OpenAiAudioConfig(api_key="secret", asr_max_pending_utterances=9)


@async_test
async def test_asr_direct_transcription_rejects_oversized_pcm_before_transport() -> None:
    called = False

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"text": "unexpected"})

    adapter = OpenAiCompatibleAsr(
        OpenAiAudioConfig(
            api_key="secret",
            asr_max_utterance_seconds=0.25,
            asr_max_utterance_bytes=8_000,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(CloudAudioInputTooLargeError):
            await adapter.transcribe_pcm16(b"\1\0" * 4_001)
        assert called is False
    finally:
        await adapter.aclose()


@async_test
async def test_asr_session_drops_continuous_oversized_speech_and_reports_error() -> None:
    adapter = OpenAiCompatibleAsr(
        OpenAiAudioConfig(
            api_key="secret",
            asr_max_utterance_seconds=0.25,
            asr_max_utterance_bytes=8_000,
        ),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        endpoint_silence_ms=200,
    )
    updates = []
    received = asyncio.Event()

    async def handler(update) -> None:
        updates.append(update)
        received.set()

    session = adapter.create_session()
    await session.start(handler)
    try:
        session.submit_pcm16(b"\x10\x27" * 4_001)
        session.submit_pcm16(b"\x10\x27" * 4_001)
        await asyncio.wait_for(received.wait(), 1)
        assert len(session.buffer) == 0
        assert len(updates) == 1
        assert isinstance(updates[0], AsrErrorUpdate)
        assert updates[0].text == "" and updates[0].final is False
        assert updates[0].error.code == "asr_utterance_too_large"
        assert updates[0].error.details["maxBytes"] == 8_000
    finally:
        await session.close()
        await adapter.aclose()


@async_test
async def test_asr_session_serializes_transcriptions_and_preserves_audio_order() -> None:
    adapter = OpenAiCompatibleAsr(
        OpenAiAudioConfig(api_key="secret", asr_max_pending_utterances=3),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        endpoint_silence_ms=200,
    )
    active = 0
    max_active = 0
    release_first = asyncio.Event()
    first_started = asyncio.Event()
    results: list[str] = []
    all_received = asyncio.Event()

    async def transcribe(pcm16: bytes) -> str:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        label = int.from_bytes(pcm16[:2], "little", signed=True) // 1_000
        try:
            if label == 1:
                first_started.set()
                await release_first.wait()
            await asyncio.sleep(0)
            return str(label)
        finally:
            active -= 1

    async def handler(update) -> None:
        if update.text:
            results.append(update.text)
            if len(results) == 3:
                all_received.set()

    adapter.transcribe_pcm16 = transcribe
    session = adapter.create_session()
    await session.start(handler)
    try:
        _submit_utterance(session, 1)
        await asyncio.wait_for(first_started.wait(), 1)
        _submit_utterance(session, 2)
        _submit_utterance(session, 3)
        release_first.set()
        await asyncio.wait_for(all_received.wait(), 1)
        assert results == ["1", "2", "3"]
        assert max_active == 1
    finally:
        await session.close()
        await adapter.aclose()


@async_test
async def test_asr_session_has_bounded_queue_and_reports_dropped_utterance_in_order() -> None:
    adapter = OpenAiCompatibleAsr(
        OpenAiAudioConfig(api_key="secret", asr_max_pending_utterances=1),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        endpoint_silence_ms=200,
    )
    release_first = asyncio.Event()
    first_started = asyncio.Event()
    updates = []
    all_received = asyncio.Event()

    async def transcribe(pcm16: bytes) -> str:
        label = int.from_bytes(pcm16[:2], "little", signed=True) // 1_000
        if label == 1:
            first_started.set()
            await release_first.wait()
        return str(label)

    async def handler(update) -> None:
        updates.append(update)
        if len(updates) == 3:
            all_received.set()

    adapter.transcribe_pcm16 = transcribe
    session = adapter.create_session()
    await session.start(handler)
    try:
        _submit_utterance(session, 1)
        await asyncio.wait_for(first_started.wait(), 1)
        _submit_utterance(session, 2)
        _submit_utterance(session, 3)
        release_first.set()
        await asyncio.wait_for(all_received.wait(), 1)
        assert [update.text for update in updates[:2]] == ["1", "2"]
        assert isinstance(updates[2], AsrErrorUpdate)
        assert updates[2].error.code == "asr_queue_full"
        assert updates[2].error.details["sequence"] == 2
    finally:
        await session.close()
        await adapter.aclose()


@async_test
async def test_asr_session_close_cancels_inflight_request_without_late_callback() -> None:
    adapter = OpenAiCompatibleAsr(
        OpenAiAudioConfig(api_key="secret"),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        endpoint_silence_ms=200,
    )
    started = asyncio.Event()
    cancelled = asyncio.Event()
    updates = []

    async def transcribe(_: bytes) -> str:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "late"

    async def handler(update) -> None:
        updates.append(update)

    adapter.transcribe_pcm16 = transcribe
    session = adapter.create_session()
    await session.start(handler)
    _submit_utterance(session, 1)
    await asyncio.wait_for(started.wait(), 1)
    await session.close()
    await asyncio.wait_for(cancelled.wait(), 1)
    await asyncio.sleep(0)
    assert updates == []
    assert session._worker is None
    await adapter.aclose()


@async_test
async def test_asr_invalidation_drops_uncancellable_late_cloud_final() -> None:
    adapter = OpenAiCompatibleAsr(
        OpenAiAudioConfig(api_key="secret"),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        endpoint_silence_ms=200,
    )
    first_started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release_stale = asyncio.Event()
    fresh_received = asyncio.Event()
    updates = []
    calls = 0

    async def transcribe(_: bytes) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                # Model a transport that observes cancellation late and still
                # produces a response. The epoch gate, not ideal cancellation,
                # is the correctness boundary.
                cancellation_seen.set()
                await release_stale.wait()
            return "stale"
        return "fresh"

    async def handler(update) -> None:
        updates.append(update)
        if update.text == "fresh":
            fresh_received.set()

    adapter.transcribe_pcm16 = transcribe
    session = adapter.create_session()
    await session.start(handler)
    try:
        _submit_utterance(session, 1)
        await asyncio.wait_for(first_started.wait(), 1)
        await session.invalidate()
        await asyncio.wait_for(cancellation_seen.wait(), 1)
        release_stale.set()
        await asyncio.sleep(0)
        _submit_utterance(session, 2)
        await asyncio.wait_for(fresh_received.wait(), 1)
        assert [update.text for update in updates] == ["fresh"]
        assert updates[0].epoch == session.epoch
    finally:
        await session.close()
        await adapter.aclose()


@async_test
async def test_rejected_asr_admission_emits_error_without_http_call() -> None:
    http_calls = 0

    async def transport_handler(_: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(200, json={"text": "must-not-run"})

    async def reject():
        return None, AsrAdmissionFailure(
            "asr_rate_limited",
            "语音识别请求过于频繁，请稍后再试",
        )

    adapter = OpenAiCompatibleAsr(
        OpenAiAudioConfig(api_key="secret"),
        transport=httpx.MockTransport(transport_handler),
        endpoint_silence_ms=200,
    )
    received = asyncio.Event()
    updates = []

    async def handler(update) -> None:
        updates.append(update)
        received.set()

    session = adapter.create_session(admit=reject)
    await session.start(handler)
    try:
        _submit_utterance(session, 1)
        await asyncio.wait_for(received.wait(), 1)
        assert http_calls == 0
        assert len(updates) == 1
        assert isinstance(updates[0], AsrErrorUpdate)
        assert updates[0].error.code == "asr_rate_limited"
    finally:
        await session.close()
        await adapter.aclose()


@async_test
async def test_asr_admission_lease_releases_after_upstream_failure() -> None:
    class Lease:
        def __init__(self) -> None:
            self.release_count = 0

        async def release(self) -> None:
            self.release_count += 1

    lease = Lease()
    http_calls = 0

    async def transport_handler(_: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(503, text="busy")

    async def admit():
        return lease, None

    adapter = OpenAiCompatibleAsr(
        OpenAiAudioConfig(api_key="secret"),
        transport=httpx.MockTransport(transport_handler),
        endpoint_silence_ms=200,
    )
    received = asyncio.Event()
    updates = []

    async def handler(update) -> None:
        updates.append(update)
        received.set()

    session = adapter.create_session(admit=admit)
    await session.start(handler)
    try:
        _submit_utterance(session, 1)
        await asyncio.wait_for(received.wait(), 1)
        assert http_calls == 1
        assert lease.release_count == 1
        assert isinstance(updates[0], AsrErrorUpdate)
    finally:
        await session.close()
        await adapter.aclose()
