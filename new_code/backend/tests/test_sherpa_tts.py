import io
import wave

import numpy as np

import pytest

from veyrasoul.integrations.sherpa_tts import (
    SherpaTtsConfig,
    SherpaTtsSynthesizer,
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
