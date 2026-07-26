import asyncio
import io
import threading
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import pytest

from veyrasoul.integrations.sherpa_tts import (
    SherpaTtsConfig,
    SherpaTtsSynthesizer,
    _apply_pronunciation_overrides,
    _voice_sid,
    wav_bytes,
)


def test_wav_bytes_encodes_mono_pcm16() -> None:
    payload = wav_bytes(np.array([-1.0, 0.0, 1.0], dtype=np.float32), 22_050)
    with wave.open(io.BytesIO(payload), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 22_050
        assert wav.getnframes() == 3


def test_health_detects_matcha_layout(tmp_path) -> None:
    for name in ("tokens.txt", "lexicon.txt", "model-steps-3.onnx", "vocos-22khz-univ.onnx"):
        (tmp_path / name).write_bytes(b"asset")
    health = SherpaTtsSynthesizer(SherpaTtsConfig(tmp_path)).health()
    assert health["ok"] is True
    assert health["engine"] == "matcha"


def test_sherpa_voice_ids_map_to_provider_sid_at_adapter_boundary() -> None:
    assert _voice_sid("default", 2) == 2
    assert _voice_sid("3", 0) == 3
    assert _voice_sid("sid:4", 0) == 4
    with pytest.raises(ValueError, match="sherpa-onnx"):
        _voice_sid("warm-female", 0)
    with pytest.raises(ValueError, match="sherpa-onnx"):
        _voice_sid("sid:999999", 0)


def test_local_tts_keeps_display_text_but_pronounces_the_product_name() -> None:
    original = "我是 Anima，欢迎回来。ANIMATION 不应被局部替换。"

    spoken = _apply_pronunciation_overrides(original, (("Anima", "安妮玛"),))

    assert spoken == "我是 安妮玛，欢迎回来。ANIMATION 不应被局部替换。"
    assert original == "我是 Anima，欢迎回来。ANIMATION 不应被局部替换。"


def test_tts_waiters_do_not_starve_the_shared_asyncio_executor(tmp_path) -> None:
    synthesizer = SherpaTtsSynthesizer(SherpaTtsConfig(tmp_path))
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def fake_synthesize(text: str, sid: int) -> tuple[bytes, str]:
        nonlocal calls
        del text, sid
        calls += 1
        entered.set()
        assert release.wait(2)
        return b"wav", "audio/wav"

    synthesizer._synthesize_sync = fake_synthesize  # type: ignore[method-assign]

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=4))
        tasks = [asyncio.create_task(synthesizer.synthesize("你好")) for _ in range(4)]
        while not entered.is_set():
            await asyncio.sleep(0)
        probe = await asyncio.wait_for(asyncio.to_thread(lambda: "executor-ready"), 0.5)
        assert probe == "executor-ready"
        release.set()
        assert await asyncio.gather(*tasks) == [(b"wav", "audio/wav")] * 4

    asyncio.run(scenario())
    assert calls == 4
