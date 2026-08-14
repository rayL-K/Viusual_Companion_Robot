from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from veyrasoul.gateway import AppServices, create_app
from veyrasoul.gateway.realtime_writer import (
    ConnectionWriter,
    RealtimeClientTooSlowError,
)
from veyrasoul.orchestration.ports import (
    SpeechAudioFormat,
    SpeechSynthesisRequest,
    SpeechSynthesisStream,
)
from veyrasoul.transport import parse_binary_frame


FORMAT = SpeechAudioFormat(
    content_type="audio/pcm",
    encoding="pcm_s16le",
    sample_rate_hz=24_000,
    channels=1,
    sample_width_bytes=2,
)

PACING_FORMAT = SpeechAudioFormat(
    content_type="audio/pcm",
    encoding="pcm_s16le",
    sample_rate_hz=8_000,
    channels=1,
    sample_width_bytes=2,
)
PCM_40_MS = b"\x01\x00" * 320


class CapturingWebSocket:
    def __init__(
        self,
        *,
        block_first_binary: bool = False,
        monotonic_clock=None,
    ) -> None:
        self.messages: list[tuple[str, object]] = []
        self.message_times: list[float] = []
        self._monotonic_clock = monotonic_clock
        self.first_binary_started = asyncio.Event()
        self.release_first_binary = asyncio.Event()
        self.close_calls: list[tuple[int, str]] = []
        if not block_first_binary:
            self.release_first_binary.set()

    async def send_bytes(self, value: bytes) -> None:
        self.messages.append(("bytes", value))
        self.message_times.append(
            self._monotonic_clock() if self._monotonic_clock else 0.0
        )
        if not self.first_binary_started.is_set():
            self.first_binary_started.set()
            await self.release_first_binary.wait()

    async def send_json(self, value: dict[str, object]) -> None:
        self.messages.append(("json", value))
        self.message_times.append(
            self._monotonic_clock() if self._monotonic_clock else 0.0
        )

    async def close(self, *, code: int, reason: str) -> None:
        self.close_calls.append((code, reason))


class BlockingJsonWebSocket(CapturingWebSocket):
    async def send_json(self, value: dict[str, object]) -> None:
        del value
        await asyncio.Event().wait()


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)
        await asyncio.sleep(0)


class SingleSentenceLlm:
    async def stream_reply(self, messages: list[dict[str, str]]):
        del messages
        yield "你好。"


class DualModeTts:
    capabilities = SimpleNamespace(tts_streaming=True)

    def __init__(self, *, block_first_stream: bool = False) -> None:
        self.batch_requests: list[SpeechSynthesisRequest] = []
        self.stream_requests: list[SpeechSynthesisRequest] = []
        self.block_first_stream = block_first_stream
        self.first_stream_closed = threading.Event()

    async def synthesize(self, request: SpeechSynthesisRequest) -> tuple[bytes, str]:
        self.batch_requests.append(request)
        return b"RIFFbatch-audio", "audio/wav"

    async def stream_synthesize(
        self,
        request: SpeechSynthesisRequest,
    ) -> SpeechSynthesisStream:
        self.stream_requests.append(request)
        request_number = len(self.stream_requests)

        async def chunks():
            try:
                yield b"\x01\x00"
                if self.block_first_stream and request_number == 1:
                    await asyncio.Event().wait()
                yield b"\x02\x00"
            finally:
                if request_number == 1:
                    self.first_stream_closed.set()

        return SpeechSynthesisStream(FORMAT, chunks())


def _app(tmp_path, tts: DualModeTts):
    return create_app(
        AppServices(
            allow_anonymous_realtime=True,
            memory_path=tmp_path / "memory.db",
            llm=SingleSentenceLlm(),
            tts=tts,
            stable_system_prompt="你是测试 Anima。",
        )
    )


def test_streaming_audio_requires_explicit_client_capability() -> None:
    writer = ConnectionWriter(
        CapturingWebSocket(),
        "session-1",
        streaming_audio_available=True,
    )
    assert writer.server_capabilities == ("reply-audio-stream-v1",)
    assert writer.streaming_audio_enabled is False
    assert writer.negotiate(["pcm16", "reply-segments"]) == ()
    assert writer.streaming_audio_enabled is False
    assert writer.negotiate(["reply-audio-stream-v1"]) == (
        "reply-audio-stream-v1",
    )
    assert writer.streaming_audio_enabled is True


def test_slow_control_client_is_closed_at_the_write_deadline() -> None:
    async def scenario() -> None:
        websocket = BlockingJsonWebSocket()
        writer = ConnectionWriter(
            websocket,
            "session-1",
            send_timeout_seconds=0.01,
        )

        with pytest.raises(RealtimeClientTooSlowError):
            await writer.event("session.heartbeat.ack")

        assert websocket.close_calls == [(1013, "realtime client too slow")]
        with pytest.raises(RealtimeClientTooSlowError):
            await writer.event("session.heartbeat.ack")

    asyncio.run(scenario())


def test_slow_stream_client_closes_the_upstream_audio_iterator() -> None:
    async def scenario() -> None:
        closed = asyncio.Event()

        async def chunks():
            try:
                yield b"\x01\x00"
                await asyncio.Event().wait()
            finally:
                closed.set()

        websocket = CapturingWebSocket(block_first_binary=True)
        writer = ConnectionWriter(
            websocket,
            "session-1",
            streaming_audio_available=True,
            send_timeout_seconds=0.01,
        )

        with pytest.raises(RealtimeClientTooSlowError):
            await writer.reply_segment(
                turn_id="turn-1",
                generation=1,
                index=0,
                text="你好。",
                audio=b"",
                content_type="audio/pcm",
                audio_stream=SpeechSynthesisStream(FORMAT, chunks()),
            )

        assert closed.is_set()
        assert websocket.close_calls == [(1013, "realtime client too slow")]

    asyncio.run(scenario())


def test_streaming_audio_frames_have_stale_gate_and_explicit_format() -> None:
    async def scenario() -> None:
        async def chunks():
            yield b"\x01\x00\x02\x00"
            yield b"\x03\x00\x04\x00"

        websocket = CapturingWebSocket()
        writer = ConnectionWriter(
            websocket,
            "session-1",
            streaming_audio_available=True,
        )
        writer.negotiate(["reply-audio-stream-v1"])
        result = await writer.reply_segment(
            turn_id="turn-1",
            generation=7,
            index=2,
            text="你好。",
            audio=b"",
            content_type="audio/pcm",
            audio_stream=SpeechSynthesisStream(FORMAT, chunks()),
        )

        assert result.audio_bytes == 8
        assert [kind for kind, _ in websocket.messages] == [
            "bytes",
            "json",
            "bytes",
            "json",
            "json",
        ]
        first_frame = parse_binary_frame(websocket.messages[0][1])
        second_frame = parse_binary_frame(websocket.messages[2][1])
        assert first_frame.flags == 0b11
        assert second_frame.flags == 0b01

        started = websocket.messages[1][1]
        assert started["type"] == "reply.segment.started"
        assert started["turnId"] == "turn-1"
        assert started["generation"] == 7
        assert started["payload"] == {
            "index": 2,
            "chunkIndex": 0,
            "audioSeq": first_frame.sequence,
            "byteLength": 4,
            "text": "你好。",
            "contentType": "audio/pcm",
            "encoding": "pcm_s16le",
            "sampleRateHz": 24_000,
            "channels": 1,
            "sampleWidthBytes": 2,
            "frameMilliseconds": 40,
            "maximumLeadMilliseconds": 140,
        }
        second = websocket.messages[3][1]
        assert second["type"] == "reply.segment.chunk"
        assert second["payload"]["audioSeq"] == second_frame.sequence
        assert second["payload"]["chunkIndex"] == 1
        completed = websocket.messages[4][1]
        assert completed["type"] == "reply.segment.completed"
        assert completed["turnId"] == "turn-1"
        assert completed["generation"] == 7
        assert completed["payload"] == {
            "index": 2,
            "chunks": 2,
            "audioBytes": 8,
        }

    asyncio.run(scenario())


def test_gateway_keeps_wav_batch_path_when_client_does_not_opt_in(tmp_path) -> None:
    tts = DualModeTts()
    with TestClient(_app(tmp_path, tts)).websocket_connect(
        "/v2/realtime?session=batch-client"
    ) as websocket:
        ready = websocket.receive_json()
        assert ready["payload"]["serverCapabilities"] == ["reply-audio-stream-v1"]
        websocket.send_json(
            {
                "v": 2,
                "type": "session.hello",
                "payload": {"capabilities": ["reply-segments"]},
            }
        )
        assert websocket.receive_json()["payload"]["capabilities"] == []
        websocket.send_json(
            {
                "v": 2,
                "type": "turn.user_text",
                "payload": {"text": "你好"},
            }
        )
        websocket.receive_json()  # thinking phase
        websocket.receive_json()  # thinking avatar
        websocket.receive_json()  # speaking avatar
        frame = parse_binary_frame(websocket.receive_bytes())
        ready_segment = websocket.receive_json()
        assert frame.payload == b"RIFFbatch-audio"
        assert frame.flags == 0
        assert ready_segment["type"] == "reply.segment.ready"
        assert tts.batch_requests and not tts.stream_requests


def test_gateway_streams_pcm_only_after_explicit_client_opt_in(tmp_path) -> None:
    tts = DualModeTts()
    with TestClient(_app(tmp_path, tts)).websocket_connect(
        "/v2/realtime?session=stream-client"
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(
            {
                "v": 2,
                "type": "session.hello",
                "payload": {"capabilities": ["reply-audio-stream-v1"]},
            }
        )
        assert websocket.receive_json()["payload"]["capabilities"] == [
            "reply-audio-stream-v1"
        ]
        websocket.send_json(
            {
                "v": 2,
                "type": "turn.user_text",
                "payload": {"text": "你好"},
            }
        )
        websocket.receive_json()  # thinking phase
        websocket.receive_json()  # thinking avatar
        websocket.receive_json()  # speaking avatar
        first = parse_binary_frame(websocket.receive_bytes())
        started = websocket.receive_json()
        second = parse_binary_frame(websocket.receive_bytes())
        chunk = websocket.receive_json()
        completed = websocket.receive_json()
        assert first.payload == b"\x01\x00" and first.flags == 0b11
        assert second.payload == b"\x02\x00" and second.flags == 0b01
        assert started["type"] == "reply.segment.started"
        assert chunk["type"] == "reply.segment.chunk"
        assert completed["type"] == "reply.segment.completed"
        assert tts.stream_requests and not tts.batch_requests


def test_cancelled_generation_closes_stream_before_next_turn_frames(tmp_path) -> None:
    tts = DualModeTts(block_first_stream=True)
    with TestClient(_app(tmp_path, tts)).websocket_connect(
        "/v2/realtime?session=cancel-stream"
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(
            {
                "v": 2,
                "type": "session.hello",
                "payload": {"capabilities": ["reply-audio-stream-v1"]},
            }
        )
        websocket.receive_json()
        websocket.send_json(
            {
                "v": 2,
                "type": "turn.user_text",
                "payload": {"text": "第一轮"},
            }
        )
        phase = websocket.receive_json()
        old_generation = phase["generation"]
        websocket.receive_json()  # thinking avatar
        websocket.receive_json()  # speaking avatar
        websocket.receive_bytes()
        started = websocket.receive_json()
        assert started["generation"] == old_generation

        websocket.send_json({"v": 2, "type": "turn.cancel", "payload": {}})
        cancelled = websocket.receive_json()
        assert cancelled["type"] == "turn.cancelled"
        assert cancelled["generation"] > old_generation
        websocket.receive_json()  # idle avatar for the cancelled turn
        assert tts.first_stream_closed.wait(1)

        websocket.send_json(
            {
                "v": 2,
                "type": "turn.user_text",
                "payload": {"text": "第二轮"},
            }
        )
        new_phase = websocket.receive_json()
        assert new_phase["type"] == "reply.phase"
        assert new_phase["generation"] > old_generation
        websocket.receive_json()
        websocket.receive_json()
        websocket.receive_bytes()
        new_started = websocket.receive_json()
        assert new_started["type"] == "reply.segment.started"
        assert new_started["generation"] == new_phase["generation"]


def test_downstream_send_applies_pull_backpressure_to_upstream() -> None:
    async def scenario() -> None:
        second_chunk_requested = asyncio.Event()

        async def chunks():
            yield b"\x01\x00"
            second_chunk_requested.set()
            yield b"\x02\x00"

        websocket = CapturingWebSocket(block_first_binary=True)
        writer = ConnectionWriter(
            websocket,
            "session-1",
            streaming_audio_available=True,
        )
        writer.negotiate(["reply-audio-stream-v1"])
        task = asyncio.create_task(
            writer.reply_segment(
                turn_id="turn-1",
                generation=1,
                index=0,
                text="hello",
                audio=b"",
                content_type="audio/pcm",
                audio_stream=SpeechSynthesisStream(FORMAT, chunks()),
            )
        )
        await asyncio.wait_for(websocket.first_binary_started.wait(), 1)
        await asyncio.sleep(0)
        assert not second_chunk_requested.is_set()
        websocket.release_first_binary.set()
        await asyncio.wait_for(task, 1)
        assert second_chunk_requested.is_set()

    asyncio.run(scenario())


def test_cancelled_downstream_closes_active_audio_iterator() -> None:
    async def scenario() -> None:
        waiting = asyncio.Event()
        closed = asyncio.Event()

        async def chunks():
            try:
                yield b"\x01\x00"
                waiting.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

        websocket = CapturingWebSocket()
        writer = ConnectionWriter(
            websocket,
            "session-1",
            streaming_audio_available=True,
        )
        writer.negotiate(["reply-audio-stream-v1"])
        task = asyncio.create_task(
            writer.reply_segment(
                turn_id="turn-1",
                generation=1,
                index=0,
                text="hello",
                audio=b"",
                content_type="audio/pcm",
                audio_stream=SpeechSynthesisStream(FORMAT, chunks()),
            )
        )
        await asyncio.wait_for(waiting.wait(), 1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:  # pragma: no cover - cancellation is the contract under test
            raise AssertionError("streaming reply task was not cancelled")
        assert closed.is_set()

    asyncio.run(scenario())


def test_fast_upstream_is_paced_by_pcm_media_time_without_delaying_first_frame() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        websocket = CapturingWebSocket(monotonic_clock=clock)
        writer = ConnectionWriter(
            websocket,
            "session-1",
            streaming_audio_available=True,
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

        async def chunks():
            for _ in range(10):
                yield PCM_40_MS

        await writer.reply_segment(
            turn_id="turn-1",
            generation=11,
            index=0,
            text="fast",
            audio=b"",
            content_type="audio/pcm",
            audio_stream=SpeechSynthesisStream(PACING_FORMAT, chunks()),
        )

        frame_times = [
            sent_at
            for (kind, _), sent_at in zip(
                websocket.messages,
                websocket.message_times,
                strict=True,
            )
            if kind == "bytes"
        ]
        assert len(frame_times) == 10
        assert frame_times[0] == 0.0
        leads = [
            (index + 1) * 0.04 - sent_at
            for index, sent_at in enumerate(frame_times)
        ]
        assert max(leads) <= 0.140_001
        assert max(leads) >= 0.139_999
        completed_time = next(
            sent_at
            for (kind, message), sent_at in zip(
                websocket.messages,
                websocket.message_times,
                strict=True,
            )
            if kind == "json" and message["type"] == "reply.segment.completed"
        )
        assert completed_time == frame_times[-1]

    asyncio.run(scenario())


def test_slow_upstream_is_not_artificially_delayed_by_pacing() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        websocket = CapturingWebSocket(monotonic_clock=clock)
        writer = ConnectionWriter(
            websocket,
            "session-1",
            streaming_audio_available=True,
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

        async def chunks():
            for index in range(4):
                if index:
                    clock.advance(0.2)
                yield PCM_40_MS

        await writer.reply_segment(
            turn_id="turn-1",
            generation=12,
            index=0,
            text="slow",
            audio=b"",
            content_type="audio/pcm",
            audio_stream=SpeechSynthesisStream(PACING_FORMAT, chunks()),
        )

        frame_times = [
            sent_at
            for (kind, _), sent_at in zip(
                websocket.messages,
                websocket.message_times,
                strict=True,
            )
            if kind == "bytes"
        ]
        assert frame_times == pytest.approx([0.0, 0.2, 0.4, 0.6])
        assert clock.sleeps == []

    asyncio.run(scenario())


def test_pacing_wait_does_not_block_control_or_perception_events() -> None:
    async def scenario() -> None:
        class ReleasableSleeper:
            def __init__(self, clock: ManualClock) -> None:
                self.clock = clock
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def __call__(self, seconds: float) -> None:
                self.started.set()
                await self.release.wait()
                self.clock.advance(seconds)

        clock = ManualClock()
        sleeper = ReleasableSleeper(clock)
        websocket = CapturingWebSocket(monotonic_clock=clock)
        writer = ConnectionWriter(
            websocket,
            "session-1",
            streaming_audio_available=True,
            monotonic_clock=clock,
            sleeper=sleeper,
        )

        async def chunks():
            for _ in range(4):
                yield PCM_40_MS

        reply = asyncio.create_task(
            writer.reply_segment(
                turn_id="turn-1",
                generation=12,
                index=0,
                text="paced",
                audio=b"",
                content_type="audio/pcm",
                audio_stream=SpeechSynthesisStream(PACING_FORMAT, chunks()),
            )
        )
        await asyncio.wait_for(sleeper.started.wait(), 1)

        # A long TTS stream must not monopolize ConnectionWriter._lock while
        # its media clock is sleeping.  Heartbeat and visual events use this
        # same event() path in production.
        await asyncio.wait_for(
            writer.event("session.heartbeat.ack", generation=12),
            0.1,
        )
        assert any(
            kind == "json" and message["type"] == "session.heartbeat.ack"
            for kind, message in websocket.messages
        )

        sleeper.release.set()
        await asyncio.wait_for(reply, 1)

    asyncio.run(scenario())


def test_two_segments_share_one_media_clock_without_boundary_drain_or_reset() -> None:
    async def render(*, split: bool) -> tuple[list[float], list[tuple[str, object]], list[float]]:
        clock = ManualClock()
        websocket = CapturingWebSocket(monotonic_clock=clock)
        writer = ConnectionWriter(
            websocket,
            "session-1",
            streaming_audio_available=True,
            monotonic_clock=clock,
            sleeper=clock.sleep,
        )

        async def chunks(count: int):
            for _ in range(count):
                yield PCM_40_MS

        counts = (5, 5) if split else (10,)
        for index, count in enumerate(counts):
            await writer.reply_segment(
                turn_id="turn-1",
                generation=13,
                index=index,
                text=f"segment-{index}",
                audio=b"",
                content_type="audio/pcm",
                audio_stream=SpeechSynthesisStream(PACING_FORMAT, chunks(count)),
            )
        frame_times = [
            sent_at
            for (kind, _), sent_at in zip(
                websocket.messages,
                websocket.message_times,
                strict=True,
            )
            if kind == "bytes"
        ]
        return frame_times, websocket.messages, websocket.message_times

    async def scenario() -> None:
        split_times, split_messages, split_message_times = await render(split=True)
        continuous_times, _, _ = await render(split=False)
        assert split_times == continuous_times
        assert max(
            (index + 1) * 0.04 - sent_at
            for index, sent_at in enumerate(split_times)
        ) <= 0.140_001

        first_completed_time = next(
            sent_at
            for (kind, message), sent_at in zip(
                split_messages,
                split_message_times,
                strict=True,
            )
            if kind == "json"
            and message["type"] == "reply.segment.completed"
            and message["payload"]["index"] == 0
        )
        assert first_completed_time == split_times[4]
        # Segment 2 starts while segment 1 still has buffered media.  The only
        # wait is the same lead-cap pacing a single uninterrupted stream uses.
        assert split_times[5] - first_completed_time <= 0.040_001
        assert 0.2 - split_times[5] > 0

    asyncio.run(scenario())


def test_timeline_reset_cancels_pacing_sleep_and_next_generation_starts_immediately() -> None:
    async def scenario() -> None:
        class BlockingSleeper:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.cancelled = asyncio.Event()

            async def __call__(self, _: float) -> None:
                self.started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.cancelled.set()

        clock = ManualClock()
        sleeper = BlockingSleeper()
        websocket = CapturingWebSocket(monotonic_clock=clock)
        writer = ConnectionWriter(
            websocket,
            "session-1",
            streaming_audio_available=True,
            monotonic_clock=clock,
            sleeper=sleeper,
        )
        old_stream_closed = asyncio.Event()

        async def old_chunks():
            try:
                for _ in range(4):
                    yield PCM_40_MS
            finally:
                old_stream_closed.set()

        task = asyncio.create_task(
            writer.reply_segment(
                turn_id="turn-old",
                generation=14,
                index=0,
                text="old",
                audio=b"",
                content_type="audio/pcm",
                audio_stream=SpeechSynthesisStream(PACING_FORMAT, old_chunks()),
            )
        )
        await asyncio.wait_for(sleeper.started.wait(), 1)
        writer.reset_audio_timeline()
        try:
            await asyncio.wait_for(task, 1)
        except asyncio.CancelledError:
            pass
        else:  # pragma: no cover - reset invalidates the generation contract
            raise AssertionError("timeline reset did not cancel pacing")
        assert sleeper.cancelled.is_set()
        assert old_stream_closed.is_set()

        first_new_frame_at = clock()

        async def new_chunks():
            yield b"\x02\x00" * 80  # 10 ms, below the lead cap

        await writer.reply_segment(
            turn_id="turn-new",
            generation=15,
            index=0,
            text="new",
            audio=b"",
            content_type="audio/pcm",
            audio_stream=SpeechSynthesisStream(PACING_FORMAT, new_chunks()),
        )
        byte_times = [
            sent_at
            for (kind, _), sent_at in zip(
                websocket.messages,
                websocket.message_times,
                strict=True,
            )
            if kind == "bytes"
        ]
        assert byte_times[-1] == first_new_frame_at

    asyncio.run(scenario())
