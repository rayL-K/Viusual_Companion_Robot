"""Turn streamed LLM text into text/audio segments that become visible together."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReadyReplySegment:
    index: int
    text: str
    audio: bytes
    content_type: str


Synthesize = Callable[[str], Awaitable[tuple[bytes, str]]]


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
    """Only yield a segment after its audio is ready, preserving text/audio synchrony."""

    def __init__(self, synthesize: Synthesize, segmenter: SentenceSegmenter | None = None) -> None:
        self.synthesize = synthesize
        self.segmenter = segmenter or SentenceSegmenter()

    async def run(self, text_stream: AsyncIterable[str]) -> AsyncIterator[ReadyReplySegment]:
        index = 0
        async for chunk in text_stream:
            for text in self.segmenter.feed(chunk):
                audio, content_type = await self.synthesize(text)
                yield ReadyReplySegment(index, text, audio, content_type)
                index += 1
        tail = self.segmenter.flush()
        if tail:
            audio, content_type = await self.synthesize(tail)
            yield ReadyReplySegment(index, tail, audio, content_type)
