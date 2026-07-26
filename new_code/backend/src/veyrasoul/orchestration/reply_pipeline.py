"""Turn streamed LLM text into text/audio segments that become visible together."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReadyReplySegment:
    index: int
    text: str
    audio: bytes
    content_type: str


Synthesize = Callable[[str], Awaitable[tuple[bytes, str]]]


@dataclass(frozen=True, slots=True)
class _PipelineItem:
    text: str = ""
    done: bool = False
    error: BaseException | None = None


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
    """Overlap LLM reading with bounded TTS work, but expose text only with ready audio."""

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
        producer = asyncio.create_task(
            self._produce(text_stream, queue),
            name="reply-segment-producer",
        )
        index = 0
        try:
            while True:
                item = await queue.get()
                if item.error is not None:
                    raise item.error
                if item.done:
                    return
                audio, content_type = await self.synthesize(item.text)
                yield ReadyReplySegment(index, item.text, audio, content_type)
                index += 1
        finally:
            if not producer.done():
                producer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer

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
