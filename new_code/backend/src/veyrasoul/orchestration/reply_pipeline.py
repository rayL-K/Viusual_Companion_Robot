"""Turn streamed LLM text into text/audio segments that become visible together."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from .ports import SpeechSynthesisStream


@dataclass(frozen=True, slots=True)
class ReadyReplySegment:
    index: int
    text: str
    audio: bytes
    content_type: str
    audio_stream: SpeechSynthesisStream | None = None


PreparedSpeech = tuple[bytes, str] | SpeechSynthesisStream
Synthesize = Callable[[str], Awaitable[PreparedSpeech]]


@dataclass(frozen=True, slots=True)
class _PipelineItem:
    text: str = ""
    done: bool = False
    error: BaseException | None = None


@dataclass(frozen=True, slots=True)
class _PreparedItem:
    segment: ReadyReplySegment | None = None
    done: bool = False
    error: BaseException | None = None


class _PrefetchedChunks:
    """Replay one primed chunk and retain explicit ownership of the upstream."""

    def __init__(self, upstream: SpeechSynthesisStream, first_chunk: bytes) -> None:
        self._upstream = upstream
        self._first_chunk: bytes | None = first_chunk
        self._closed = False

    def __aiter__(self) -> _PrefetchedChunks:
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration
        if self._first_chunk is not None:
            chunk = self._first_chunk
            self._first_chunk = None
            return chunk
        try:
            return await self._upstream.chunks.__anext__()
        except StopAsyncIteration:
            await self.aclose()
            raise
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._first_chunk = None
        await self._upstream.aclose()


class SentenceSegmenter:
    def __init__(self, *, minimum_chars: int = 2, maximum_chars: int = 64) -> None:
        self.minimum_chars = max(1, int(minimum_chars))
        self.maximum_chars = max(self.minimum_chars, int(maximum_chars))
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        self._buffer += str(chunk or "")
        segments: list[str] = []
        while self._buffer:
            boundary = self._find_boundary()
            if boundary is None:
                break
            segment = self._buffer[:boundary].strip()
            self._buffer = self._buffer[boundary:].lstrip()
            if segment:
                segments.append(segment)
        return segments

    def flush(self) -> str:
        value = self._buffer.strip()
        self._buffer = ""
        return value

    def _find_boundary(self) -> int | None:
        if len(self._buffer) >= self.maximum_chars:
            soft = max(self._buffer.rfind(mark, 0, self.maximum_chars) for mark in ("，", ",", " "))
            return soft + 1 if soft >= self.minimum_chars else self.maximum_chars
        if len(self._buffer) < self.minimum_chars:
            return None
        for index, character in enumerate(self._buffer, start=1):
            if index >= self.minimum_chars and character in "。！？!?；;\n":
                return index
        return None


class ReplyPipeline:
    """Overlap LLM and one-segment TTS lookahead without exposing text early."""

    def __init__(
        self,
        synthesize: Synthesize,
        segmenter: SentenceSegmenter | None = None,
        *,
        max_pending_segments: int = 2,
    ) -> None:
        self.synthesize = synthesize
        self.segmenter = segmenter or SentenceSegmenter()
        self.max_pending_segments = max(1, min(8, int(max_pending_segments)))

    async def run(self, text_stream: AsyncIterable[str]) -> AsyncIterator[ReadyReplySegment]:
        queue: asyncio.Queue[_PipelineItem] = asyncio.Queue(self.max_pending_segments)
        ready: asyncio.Queue[_PreparedItem] = asyncio.Queue(maxsize=1)
        # A queued prepared segment owns this permit.  The preparer therefore
        # cannot start segment N+2 while N is playing and N+1 is prefetched.
        ready_slot = asyncio.Semaphore(1)
        producer = asyncio.create_task(
            self._produce(text_stream, queue),
            name="reply-segment-producer",
        )
        preparer = asyncio.create_task(
            self._prepare(queue, ready, ready_slot),
            name="reply-segment-tts-lookahead",
        )
        try:
            while True:
                item = await ready.get()
                ready_slot.release()
                if item.error is not None:
                    raise item.error
                if item.done:
                    return
                segment = item.segment
                if segment is None:
                    raise RuntimeError("reply preparer returned an empty item")
                try:
                    yield segment
                finally:
                    if segment.audio_stream is not None:
                        await _close_speech_stream(segment.audio_stream)
        finally:
            for task in (preparer, producer):
                if not task.done():
                    task.cancel()
            await asyncio.gather(preparer, producer, return_exceptions=True)
            while True:
                try:
                    item = ready.get_nowait()
                except asyncio.QueueEmpty:
                    break
                ready_slot.release()
                if item.segment is not None and item.segment.audio_stream is not None:
                    await _close_speech_stream(item.segment.audio_stream)

    async def _prepare(
        self,
        queue: asyncio.Queue[_PipelineItem],
        ready: asyncio.Queue[_PreparedItem],
        ready_slot: asyncio.Semaphore,
    ) -> None:
        index = 0
        while True:
            await ready_slot.acquire()
            permit_transferred = False
            owned_stream: SpeechSynthesisStream | None = None
            try:
                item = await queue.get()
                if item.error is not None:
                    raise item.error
                if item.done:
                    await ready.put(_PreparedItem(done=True))
                    permit_transferred = True
                    return

                prepared = await self.synthesize(item.text)
                if isinstance(prepared, SpeechSynthesisStream):
                    owned_stream = prepared
                    prepared = await _prime_speech_stream(prepared)
                    owned_stream = prepared
                    segment = ReadyReplySegment(
                        index,
                        item.text,
                        b"",
                        prepared.format.content_type,
                        prepared,
                    )
                else:
                    audio, content_type = prepared
                    segment = ReadyReplySegment(index, item.text, audio, content_type)

                await ready.put(_PreparedItem(segment=segment))
                permit_transferred = True
                owned_stream = None
                index += 1
            except asyncio.CancelledError:
                if owned_stream is not None:
                    await _close_speech_stream(owned_stream)
                raise
            except BaseException as exc:
                if owned_stream is not None:
                    await _close_speech_stream(owned_stream)
                await ready.put(_PreparedItem(error=exc))
                permit_transferred = True
                return
            finally:
                if not permit_transferred:
                    ready_slot.release()

    async def _produce(
        self,
        text_stream: AsyncIterable[str],
        queue: asyncio.Queue[_PipelineItem],
    ) -> None:
        try:
            async for chunk in text_stream:
                for text in self.segmenter.feed(chunk):
                    await queue.put(_PipelineItem(text=text))
            tail = self.segmenter.flush()
            if tail:
                await queue.put(_PipelineItem(text=tail))
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            await queue.put(_PipelineItem(error=exc))
        else:
            await queue.put(_PipelineItem(done=True))


async def _prime_speech_stream(stream: SpeechSynthesisStream) -> SpeechSynthesisStream:
    """Pull exactly through the first non-empty chunk and replay it unchanged."""

    try:
        while True:
            chunk = await stream.chunks.__anext__()
            if chunk:
                return SpeechSynthesisStream(
                    stream.format,
                    _PrefetchedChunks(stream, chunk),
                )
    except StopAsyncIteration as exc:
        await _close_speech_stream(stream)
        raise RuntimeError("streaming TTS returned no audio") from exc
    except BaseException:
        await _close_speech_stream(stream)
        raise


async def _close_speech_stream(stream: SpeechSynthesisStream) -> None:
    with contextlib.suppress(Exception, asyncio.CancelledError):
        await stream.aclose()
