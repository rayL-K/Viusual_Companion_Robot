import io
import wave

from veyrasoul.gateway.demo import _tone_wav


def test_demo_tone_is_valid_short_wav() -> None:
    payload = _tone_wav(440, 0.1)
    with wave.open(io.BytesIO(payload), "rb") as wav:
        assert wav.getframerate() == 16_000
        assert wav.getnchannels() == 1
        assert wav.getnframes() == 1_600
