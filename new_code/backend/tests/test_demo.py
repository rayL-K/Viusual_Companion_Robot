import io
import wave

import asyncio

from veyrasoul.gateway.demo import DemoLlm, _tone_wav


def test_demo_tone_is_valid_short_wav() -> None:
    payload = _tone_wav(440, 0.1)
    with wave.open(io.BytesIO(payload), "rb") as wav:
        assert wav.getframerate() == 16_000
        assert wav.getnchannels() == 1
        assert wav.getnframes() == 1_600


def test_demo_llm_has_a_cancellable_slow_path() -> None:
    async def scenario() -> None:
        client = DemoLlm()
        stream = client.stream_reply([{"role": "user", "content": "立即打断"}])
        chunks = [chunk async for chunk in stream]
        assert "新的回复已经接管" in "".join(chunks)

    asyncio.run(scenario())
