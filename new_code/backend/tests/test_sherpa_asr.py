from __future__ import annotations

import asyncio

from veyrasoul.integrations.sherpa_asr import SherpaAsrSession
from veyrasoul.orchestration.ports import AsrUpdate


class FakeStreamingRecognizer:
    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def _decode(self, stream: object, pcm16: bytes) -> tuple[str, bool]:
        self.calls.append(pcm16)
        if len(self.calls) == 1:
            return "你", False
        return "你好", True


def test_streaming_session_emits_partial_then_endpoint_final() -> None:
    async def scenario() -> None:
        owner = FakeStreamingRecognizer()
        updates: list[AsrUpdate] = []
        partial_ready = asyncio.Event()
        final_ready = asyncio.Event()

        async def handle(update: AsrUpdate) -> None:
            updates.append(update)
            if update.final:
                final_ready.set()
            else:
                partial_ready.set()

        session = SherpaAsrSession(owner, object(), queue_frames=10)  # type: ignore[arg-type]
        await session.start(handle)
        session.submit_pcm16(b"\x01\x00" * 320)
        await asyncio.wait_for(partial_ready.wait(), timeout=1.0)
        partial_ready.clear()
        session.submit_pcm16(b"\x02\x00" * 320)
        await asyncio.wait_for(final_ready.wait(), timeout=1.0)
        await session.close()

        assert updates == [
            AsrUpdate(text="你", final=False),
            AsrUpdate(text="你好", final=False),
            AsrUpdate(text="你好", final=True),
        ]
        assert len(owner.calls) == 2

    asyncio.run(scenario())


def test_streaming_session_rejects_invalid_pcm_and_submission_before_start() -> None:
    owner = FakeStreamingRecognizer()
    session = SherpaAsrSession(owner, object(), queue_frames=10)  # type: ignore[arg-type]

    try:
        session.submit_pcm16(b"\x00\x00")
    except RuntimeError as exc:
        assert "not running" in str(exc)
    else:
        raise AssertionError("submission before start must fail")

    async def scenario() -> None:
        await session.start(lambda update: asyncio.sleep(0))
        try:
            session.submit_pcm16(b"\x00")
        except ValueError as exc:
            assert "complete int16" in str(exc)
        else:
            raise AssertionError("odd-length PCM16 must fail")
        await session.close()

    asyncio.run(scenario())
