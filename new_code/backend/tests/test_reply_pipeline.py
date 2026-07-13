from __future__ import annotations

import asyncio

from veyrasoul.orchestration.reply_pipeline import ReplyPipeline, SentenceSegmenter
from veyrasoul.orchestration.turn_service import _limit_stream


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
