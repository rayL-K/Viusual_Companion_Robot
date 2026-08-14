from __future__ import annotations

import asyncio

import pytest

from veyrasoul.orchestration.ports import SpeechAudioFormat, SpeechSynthesisStream
from veyrasoul.orchestration.reply_pipeline import ReplyPipeline, SentenceSegmenter
from veyrasoul.orchestration.turn_service import _limit_stream


PCM_FORMAT = SpeechAudioFormat(
    content_type="audio/pcm",
    encoding="pcm_s16le",
    sample_rate_hz=24_000,
    channels=1,
    sample_width_bytes=2,
)


def test_sentence_segmenter_handles_streamed_chinese_punctuation() -> None:
    segmenter = SentenceSegmenter(minimum_chars=4)
    assert segmenter.feed("主人，我看") == []
    assert segmenter.feed("见你坐在书桌前。还戴着眼镜！") == ["主人，我看见你坐在书桌前。", "还戴着眼镜！"]


def test_pipeline_yields_only_after_audio_exists() -> None:
    async def scenario() -> None:
        async def stream():
            yield "第一句话。第二句话。"

        async def synthesize(text: str) -> tuple[bytes, str]:
            return text.encode("utf-8"), "audio/wav"

        segments = [segment async for segment in ReplyPipeline(synthesize).run(stream())]
        assert [segment.text for segment in segments] == ["第一句话。", "第二句话。"]
        assert all(segment.audio for segment in segments)

    asyncio.run(scenario())


def test_pipeline_reads_ahead_while_first_segment_is_synthesizing() -> None:
    async def scenario() -> None:
        first_tts_started = asyncio.Event()
        allow_first_tts = asyncio.Event()
        second_sentence_consumed = asyncio.Event()

        async def stream():
            yield "第一句话。"
            second_sentence_consumed.set()
            yield "第二句话。"

        async def synthesize(text: str) -> tuple[bytes, str]:
            if text == "第一句话。":
                first_tts_started.set()
                await allow_first_tts.wait()
            return text.encode("utf-8"), "audio/wav"

        async def collect():
            return [segment async for segment in ReplyPipeline(synthesize).run(stream())]

        task = asyncio.create_task(collect())
        await asyncio.wait_for(first_tts_started.wait(), 1)
        await asyncio.wait_for(second_sentence_consumed.wait(), 1)
        assert not task.done()
        allow_first_tts.set()
        segments = await asyncio.wait_for(task, 1)
        assert [segment.text for segment in segments] == ["第一句话。", "第二句话。"]

    asyncio.run(scenario())


def test_pipeline_prefetches_next_stream_first_chunk_while_current_plays() -> None:
    async def scenario() -> None:
        first_playing = asyncio.Event()
        release_first_tail = asyncio.Event()
        second_requested = asyncio.Event()
        second_primed = asyncio.Event()
        third_requested = asyncio.Event()

        async def text_stream():
            yield "第一句话。第二句话。第三句话。"

        async def synthesize(text: str) -> SpeechSynthesisStream:
            if text == "第一句话。":

                async def first_chunks():
                    yield b"first-head"
                    first_playing.set()
                    await release_first_tail.wait()
                    yield b"first-tail"

                return SpeechSynthesisStream(PCM_FORMAT, first_chunks())

            if text == "第二句话。":
                second_requested.set()

            async def second_chunks():
                yield b""
                if text == "第二句话。":
                    second_primed.set()
                    yield b"second-head"
                    yield b"second-tail"
                else:
                    third_requested.set()
                    yield b"third-head"

            return SpeechSynthesisStream(PCM_FORMAT, second_chunks())

        pipeline = ReplyPipeline(synthesize)
        segments = pipeline.run(text_stream())
        first = await asyncio.wait_for(anext(segments), 1)
        assert first.audio_stream is not None

        async def collect_current() -> list[bytes]:
            return [chunk async for chunk in first.audio_stream.chunks]

        playing = asyncio.create_task(collect_current())
        await asyncio.wait_for(first_playing.wait(), 1)
        await asyncio.wait_for(second_requested.wait(), 1)
        await asyncio.wait_for(second_primed.wait(), 1)
        assert not playing.done()
        assert not third_requested.is_set()

        release_first_tail.set()
        assert await asyncio.wait_for(playing, 1) == [b"first-head", b"first-tail"]

        second = await asyncio.wait_for(anext(segments), 1)
        assert second.audio_stream is not None
        await asyncio.wait_for(third_requested.wait(), 1)
        assert [chunk async for chunk in second.audio_stream.chunks] == [
            b"second-head",
            b"second-tail",
        ]
        third = await asyncio.wait_for(anext(segments), 1)
        assert third.audio_stream is not None
        assert [chunk async for chunk in third.audio_stream.chunks] == [b"third-head"]
        with pytest.raises(StopAsyncIteration):
            await anext(segments)

    asyncio.run(scenario())


def test_pipeline_cancel_closes_current_and_prefetched_streams() -> None:
    async def scenario() -> None:
        closed: list[str] = []
        second_primed = asyncio.Event()

        async def text_stream():
            yield "第一句话。第二句话。"

        async def synthesize(text: str) -> SpeechSynthesisStream:
            label = "first" if text == "第一句话。" else "second"

            async def chunks():
                try:
                    if label == "second":
                        second_primed.set()
                    yield f"{label}-head".encode()
                    await asyncio.Event().wait()
                finally:
                    closed.append(label)

            return SpeechSynthesisStream(PCM_FORMAT, chunks())

        pipeline = ReplyPipeline(synthesize)
        segments = pipeline.run(text_stream())
        first = await asyncio.wait_for(anext(segments), 1)
        assert first.audio_stream is not None
        assert await anext(first.audio_stream.chunks) == b"first-head"
        await asyncio.wait_for(second_primed.wait(), 1)

        await asyncio.wait_for(segments.aclose(), 1)
        assert sorted(closed) == ["first", "second"]

    asyncio.run(scenario())


def test_reply_character_limit_closes_upstream_without_consuming_extra_chunks() -> None:
    async def scenario() -> None:
        consumed: list[str] = []
        closed = False

        async def stream():
            nonlocal closed
            try:
                for chunk in ("12345", "67890", "should-not-be-read"):
                    consumed.append(chunk)
                    yield chunk
            finally:
                closed = True

        result = "".join([chunk async for chunk in _limit_stream(stream(), 8)])
        assert result == "12345678"
        assert consumed == ["12345", "67890"]
        assert closed is True

    asyncio.run(scenario())
