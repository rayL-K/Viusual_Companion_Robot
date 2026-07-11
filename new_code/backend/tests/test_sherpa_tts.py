import io
import wave

import numpy as np

from veyrasoul.integrations.sherpa_tts import SherpaTtsConfig, SherpaTtsSynthesizer, wav_bytes


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
