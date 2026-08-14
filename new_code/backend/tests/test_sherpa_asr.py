from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from veyrasoul.integrations.sherpa_asr import SherpaAsrConfig, SherpaAsrSession, SherpaStreamingAsr
from veyrasoul.orchestration.ports import AsrUpdate


class FakeStreamingRecognizer:
    def __init__(self) -> None:
        self.calls: list[bytes] = []

    async def decode(self, stream: object, pcm16: bytes) -> tuple[str, bool]:
        self.calls.append(pcm16)
        if len(self.calls) == 1:
            return "你", False
        return "你好", True

    async def reset(self, stream: object) -> None:
        del stream


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


def test_asr_waiters_do_not_starve_the_shared_asyncio_executor(tmp_path) -> None:
    owner = SherpaStreamingAsr(SherpaAsrConfig(tmp_path))
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def fake_decode(stream: object, pcm16: bytes) -> tuple[str, bool]:
        nonlocal calls
        del stream, pcm16
        calls += 1
        entered.set()
        assert release.wait(2)
        return "", False

    owner._decode = fake_decode  # type: ignore[method-assign]

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=4))
        tasks = [
            asyncio.create_task(owner.decode(object(), b"\x00\x00" * 320))
            for _ in range(4)
        ]
        while not entered.is_set():
            await asyncio.sleep(0)
        probe = await asyncio.wait_for(asyncio.to_thread(lambda: "executor-ready"), 0.5)
        assert probe == "executor-ready"
        release.set()
        assert await asyncio.gather(*tasks) == [("", False)] * 4

    asyncio.run(scenario())
    assert calls == 4


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


def test_invalidation_drops_stale_native_decode_and_resets_stream() -> None:
    class ControlledRecognizer:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.decode_calls = 0
            self.reset_calls = 0

        async def decode(self, stream: object, pcm16: bytes) -> tuple[str, bool]:
            del stream, pcm16
            self.decode_calls += 1
            if self.decode_calls == 1:
                self.started.set()
                await self.release.wait()
                return "stale", True
            return "fresh", True

        async def reset(self, stream: object) -> None:
            del stream
            self.reset_calls += 1

    async def scenario() -> None:
        owner = ControlledRecognizer()
        updates: list[AsrUpdate] = []
        fresh_final = asyncio.Event()

        async def handler(update: AsrUpdate) -> None:
            updates.append(update)
            if update.final and update.text == "fresh":
                fresh_final.set()

        session = SherpaAsrSession(owner, object(), queue_frames=10)  # type: ignore[arg-type]
        await session.start(handler)
        session.submit_pcm16(b"\x01\x00" * 320)
        await asyncio.wait_for(owner.started.wait(), 1)
        await asyncio.wait_for(session.invalidate(), 0.1)
        session.submit_pcm16(b"\x02\x00" * 320)
        owner.release.set()
        await asyncio.wait_for(fresh_final.wait(), 1)
        await session.close()

        assert owner.reset_calls >= 1
        assert [update.text for update in updates] == ["fresh", "fresh"]
        assert all(update.epoch == 1 for update in updates)

    asyncio.run(scenario())
