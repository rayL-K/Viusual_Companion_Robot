from __future__ import annotations

import asyncio

from veyrasoul.orchestration.reply_pipeline import ReplyPipeline, SentenceSegmenter


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
