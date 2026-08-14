"""Serialized, deadline-bounded realtime WebSocket output.

This module owns the wire sequence, reply-audio framing and media-clock pacing
for one realtime connection.  The gateway route only coordinates lifecycle and
turn state; it does not need to know the details of audio frame scheduling.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from veyrasoul.orchestration.ports import SpeechSynthesisStream
from veyrasoul.transport import BinaryKind, build_binary_frame


_AUDIO_STREAM_CAPABILITY = "reply-audio-stream-v1"
_AUDIO_STREAM_FLAG = 0b0000_0001
_AUDIO_STREAM_START_FLAG = 0b0000_0010
_AUDIO_STREAM_FRAME_MILLISECONDS = 40
_AUDIO_STREAM_MAX_LEAD_SECONDS = 0.14


@dataclass(frozen=True, slots=True)
class ReplyWriteResult:
    first_frame_sent_ns: int
    audio_bytes: int


class RealtimeClientTooSlowError(ConnectionError):
    """The peer stopped draining WebSocket output within the server deadline."""


class ConnectionWriter:
    """Write one ordered realtime stream without unbounded socket waits."""

    def __init__(
        self,
        websocket: WebSocket,
        session_id: str,
        *,
        streaming_audio_available: bool = False,
        send_timeout_seconds: float = 5.0,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if send_timeout_seconds <= 0:
            raise ValueError("send_timeout_seconds must be positive")
        self.websocket = websocket
        self.session_id = session_id
        self.streaming_audio_available = streaming_audio_available
        self.streaming_audio_enabled = False
        self._monotonic_clock = monotonic_clock
        self._sleeper = sleeper
        self._send_timeout_seconds = float(send_timeout_seconds)
        self._send_failed = False
        self._audio_playout_deadline = 0.0
        self._audio_timeline_started = False
        self._audio_timeline_generation: int | None = None
        self._audio_timeline_epoch = 0
        self._audio_timeline_reset = asyncio.Event()
        self._sequence = 0
        self._lock = asyncio.Lock()

    @property
    def server_capabilities(self) -> tuple[str, ...]:
        return (
            (_AUDIO_STREAM_CAPABILITY,)
            if self.streaming_audio_available
            else ()
        )

    def negotiate(self, capabilities: object) -> tuple[str, ...]:
        declared = (
            {
                item
                for item in capabilities
                if isinstance(item, str) and 0 < len(item) <= 64
            }
            if isinstance(capabilities, list)
            else set()
        )
        self.streaming_audio_enabled = (
            self.streaming_audio_available
            and _AUDIO_STREAM_CAPABILITY in declared
        )
        return (
            (_AUDIO_STREAM_CAPABILITY,)
            if self.streaming_audio_enabled
            else ()
        )

    def configure_streaming_audio(self, synthesizer: object) -> None:
        capabilities = getattr(synthesizer, "capabilities", None)
        self.streaming_audio_available = (
            callable(getattr(synthesizer, "stream_synthesize", None))
            and bool(getattr(capabilities, "tts_streaming", False))
        )
        if not self.streaming_audio_available:
            self.streaming_audio_enabled = False

    def reset_audio_timeline(self) -> None:
        # Wake an in-flight pacing wait as well as clearing its media clock.  A
        # cancelled generation must not retain either queued lead or a sleeper
        # that can delay the replacement turn.
        self._audio_timeline_epoch += 1
        self._audio_timeline_reset.set()
        self._audio_timeline_reset = asyncio.Event()
        self._audio_playout_deadline = 0.0
        self._audio_timeline_started = False
        self._audio_timeline_generation = None

    def _select_audio_generation(self, generation: int) -> None:
        if self._audio_timeline_generation == generation:
            return
        self.reset_audio_timeline()
        self._audio_timeline_generation = generation

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    async def _send(self, operation: Callable[[], Awaitable[None]]) -> None:
        if self._send_failed:
            raise RealtimeClientTooSlowError("realtime client is no longer writable")
        try:
            await asyncio.wait_for(operation(), timeout=self._send_timeout_seconds)
        except asyncio.TimeoutError:
            self._send_failed = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    self.websocket.close(code=1013, reason="realtime client too slow"),
                    timeout=min(1.0, self._send_timeout_seconds),
                )
            raise RealtimeClientTooSlowError(
                "realtime client stopped reading WebSocket output"
            ) from None

    async def event(
        self,
        event_type: str,
        *,
        turn_id: str = "",
        generation: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            message = {
                "v": 2,
                "type": event_type,
                "sessionId": self.session_id,
                "turnId": turn_id,
                "generation": generation,
                "seq": self._next_sequence(),
                "sentAtMs": int(time.time() * 1000),
                "payload": payload or {},
            }
            await self._send(lambda: self.websocket.send_json(message))

    async def reply_segment(
        self,
        *,
        turn_id: str,
        generation: int,
        index: int,
        text: str,
        audio: bytes,
        content_type: str,
        audio_stream: SpeechSynthesisStream | None = None,
    ) -> ReplyWriteResult:
        """Send audio first, then expose its text in WebSocket order."""

        if audio_stream is not None:
            return await self._reply_stream(
                turn_id=turn_id,
                generation=generation,
                index=index,
                text=text,
                audio_stream=audio_stream,
            )
        async with self._lock:
            audio_sequence = self._next_sequence()
            frame = build_binary_frame(
                BinaryKind.AUDIO,
                audio_sequence,
                int(time.time() * 1000),
                audio,
            )
            await self._send(lambda: self.websocket.send_bytes(frame))
            first_frame_sent_ns = time.monotonic_ns()
            message = {
                "v": 2,
                "type": "reply.segment.ready",
                "sessionId": self.session_id,
                "turnId": turn_id,
                "generation": generation,
                "seq": self._next_sequence(),
                "sentAtMs": int(time.time() * 1000),
                "payload": {
                    "index": index,
                    "text": text,
                    "audioSeq": audio_sequence,
                    "contentType": content_type,
                },
            }
            await self._send(lambda: self.websocket.send_json(message))
            return ReplyWriteResult(first_frame_sent_ns, len(audio))

    async def _reply_stream(
        self,
        *,
        turn_id: str,
        generation: int,
        index: int,
        text: str,
        audio_stream: SpeechSynthesisStream,
    ) -> ReplyWriteResult:
        """Bracket pull-based PCM chunks with stale-gatable control events."""

        chunk_index = 0
        audio_bytes = 0
        first_frame_sent_ns = 0
        try:
            audio_format = audio_stream.format
            if audio_format.encoding != "pcm_s16le":
                raise RuntimeError("reply-audio-stream-v1 requires pcm_s16le")
            frame_alignment = (
                audio_format.channels * audio_format.sample_width_bytes
            )
            bytes_per_second = audio_format.sample_rate_hz * frame_alignment
            maximum_frame_bytes = max(
                frame_alignment,
                bytes_per_second * _AUDIO_STREAM_FRAME_MILLISECONDS // 1_000,
            )
            maximum_frame_bytes -= maximum_frame_bytes % frame_alignment
            async for chunk in audio_stream.chunks:
                payload = bytes(chunk)
                if not payload:
                    continue
                if len(payload) % frame_alignment:
                    raise RuntimeError(
                        "streaming TTS returned an incomplete PCM frame"
                    )
                for offset in range(0, len(payload), maximum_frame_bytes):
                    frame = payload[offset : offset + maximum_frame_bytes]
                    # Pacing must never hold the connection-wide send lock:
                    # heartbeat, visual semantics and cancellation events need
                    # to remain realtime while speech is playing.  Only the
                    # binary frame and its metadata event are one atomic pair.
                    await self._reserve_audio_frame(
                        len(frame) / bytes_per_second,
                        generation=generation,
                    )
                    async with self._lock:
                        audio_sequence = self._next_sequence()
                        flags = _AUDIO_STREAM_FLAG
                        event_type = "reply.segment.chunk"
                        event_payload: dict[str, Any] = {
                            "index": index,
                            "chunkIndex": chunk_index,
                            "audioSeq": audio_sequence,
                            "byteLength": len(frame),
                        }
                        if chunk_index == 0:
                            flags |= _AUDIO_STREAM_START_FLAG
                            event_type = "reply.segment.started"
                            event_payload.update(
                                {
                                    "text": text,
                                    "contentType": audio_format.content_type,
                                    "encoding": audio_format.encoding,
                                    "sampleRateHz": audio_format.sample_rate_hz,
                                    "channels": audio_format.channels,
                                    "sampleWidthBytes": audio_format.sample_width_bytes,
                                    "frameMilliseconds": (
                                        _AUDIO_STREAM_FRAME_MILLISECONDS
                                    ),
                                    "maximumLeadMilliseconds": round(
                                        _AUDIO_STREAM_MAX_LEAD_SECONDS * 1_000
                                    ),
                                }
                            )
                        binary_frame = build_binary_frame(
                            BinaryKind.AUDIO,
                            audio_sequence,
                            int(time.time() * 1000),
                            frame,
                            flags=flags,
                        )
                        await self._send(
                            lambda: self.websocket.send_bytes(binary_frame)
                        )
                        if chunk_index == 0:
                            first_frame_sent_ns = time.monotonic_ns()
                        message = {
                            "v": 2,
                            "type": event_type,
                            "sessionId": self.session_id,
                            "turnId": turn_id,
                            "generation": generation,
                            "seq": self._next_sequence(),
                            "sentAtMs": int(time.time() * 1000),
                            "payload": event_payload,
                        }
                        await self._send(lambda: self.websocket.send_json(message))
                    audio_bytes += len(frame)
                    chunk_index += 1
            if chunk_index == 0:
                raise RuntimeError("streaming TTS returned no audio")
            async with self._lock:
                message = {
                    "v": 2,
                    "type": "reply.segment.completed",
                    "sessionId": self.session_id,
                    "turnId": turn_id,
                    "generation": generation,
                    "seq": self._next_sequence(),
                    "sentAtMs": int(time.time() * 1000),
                    "payload": {
                        "index": index,
                        "chunks": chunk_index,
                        "audioBytes": audio_bytes,
                    },
                }
                await self._send(lambda: self.websocket.send_json(message))
            return ReplyWriteResult(first_frame_sent_ns, audio_bytes)
        finally:
            with contextlib.suppress(Exception):
                await audio_stream.aclose()

    async def _reserve_audio_frame(
        self,
        duration_seconds: float,
        *,
        generation: int,
    ) -> None:
        self._select_audio_generation(generation)
        epoch = self._audio_timeline_epoch
        reset_event = self._audio_timeline_reset
        now = self._monotonic_clock()
        if not self._audio_timeline_started:
            self._audio_timeline_started = True
            self._audio_playout_deadline = now + duration_seconds
            return

        while True:
            prospective_deadline = (
                max(now, self._audio_playout_deadline) + duration_seconds
            )
            delay = (
                prospective_deadline
                - now
                - _AUDIO_STREAM_MAX_LEAD_SECONDS
            )
            if delay <= 0:
                break
            await self._sleep_unless_timeline_reset(delay, reset_event)
            self._assert_audio_timeline(generation, epoch)
            now = self._monotonic_clock()
        self._audio_playout_deadline = prospective_deadline

    def _assert_audio_timeline(self, generation: int, epoch: int) -> None:
        if (
            self._audio_timeline_generation != generation
            or self._audio_timeline_epoch != epoch
        ):
            raise asyncio.CancelledError

    async def _sleep_unless_timeline_reset(
        self,
        delay: float,
        reset_event: asyncio.Event,
    ) -> None:
        sleep_task = asyncio.ensure_future(self._sleeper(delay))
        reset_task = asyncio.create_task(reset_event.wait())
        try:
            done, _ = await asyncio.wait(
                (sleep_task, reset_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if reset_task in done:
                raise asyncio.CancelledError
            await sleep_task
        finally:
            for task in (sleep_task, reset_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                sleep_task,
                reset_task,
                return_exceptions=True,
            )
