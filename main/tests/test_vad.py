from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.perception.vad import (
    VADConfig,
    VAD_SPEECH_END,
    VAD_SPEECH_START,
    VoiceActivityDetector,
)


class FakeVad:
    def __init__(self, speech: bool) -> None:
        self.speech = speech

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return self.speech


class VoiceActivityDetectorTests(unittest.TestCase):
    def test_state_machine_emits_start_and_end(self) -> None:
        detector = VoiceActivityDetector(VADConfig(frame_ms=30, padding_ms=300))
        frame = bytes(16000 * 30 // 1000 * 2)
        detector._vad = FakeVad(True)  # type: ignore[assignment]

        self.assertEqual(list(detector.process_chunk(frame)), [VAD_SPEECH_START])

        detector._vad = FakeVad(False)  # type: ignore[assignment]
        events = []
        for _ in range(10):
            events.extend(detector.process_chunk(frame))
        self.assertEqual(events, [VAD_SPEECH_END])

    def test_invalid_frame_duration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "frame_ms"):
            VoiceActivityDetector(VADConfig(frame_ms=25))


if __name__ == "__main__":
    unittest.main()
