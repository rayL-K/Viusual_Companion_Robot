from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.perception.active_speaker import (
    ActiveSpeakerBusyError,
    ActiveSpeakerRecognizer,
)


class FakeEngine:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.calls = 0

    def load(self, _path: str) -> None: pass
    def is_loaded(self) -> bool: return True
    def unload(self) -> None: pass
    def run(self, output_names, input_feed):  # type: ignore[no-untyped-def]
        score = self.scores[self.calls]
        self.calls += 1
        count = input_feed["face_frames"].shape[1]
        return [np.full(count, score, dtype=np.float32)]


@dataclass
class Track:
    track_id: int
    crops: tuple[np.ndarray, ...]
    profile_id: str | None = None
    name: str | None = None


class ActiveSpeakerTests(unittest.TestCase):
    def test_concurrent_request_is_rejected_instead_of_queuing(self) -> None:
        recognizer = ActiveSpeakerRecognizer(Path("model.onnx"), engine=FakeEngine([0.8]))  # type: ignore[arg-type]
        recognizer._lock.acquire()  # type: ignore[attr-defined]
        try:
            with self.assertRaises(ActiveSpeakerBusyError):
                recognizer.analyze(np.zeros(16_000, dtype=np.int16), [])
        finally:
            recognizer._lock.release()  # type: ignore[attr-defined]

    def test_clear_best_candidate_is_confirmed(self) -> None:
        engine = FakeEngine([0.82, 0.41])
        recognizer = ActiveSpeakerRecognizer(Path("model.onnx"), engine=engine)  # type: ignore[arg-type]
        tracks = [
            Track(0, tuple(np.zeros((112, 112), dtype=np.uint8) for _ in range(8)), "p1", "主人"),
            Track(1, tuple(np.zeros((112, 112), dtype=np.uint8) for _ in range(8))),
        ]
        with patch(
            "visual_companion_robot.perception.active_speaker._mfcc",
            return_value=np.zeros((200, 13), dtype=np.float32),
        ):
            result = recognizer.analyze(np.zeros(32_000, dtype=np.int16), tracks)

        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["speaker"]["name"], "主人")

    def test_close_candidates_remain_unknown(self) -> None:
        engine = FakeEngine([0.70, 0.66])
        recognizer = ActiveSpeakerRecognizer(Path("model.onnx"), engine=engine)  # type: ignore[arg-type]
        tracks = [Track(index, tuple(np.zeros((112, 112), dtype=np.uint8) for _ in range(6))) for index in range(2)]
        with patch(
            "visual_companion_robot.perception.active_speaker._mfcc",
            return_value=np.zeros((100, 13), dtype=np.float32),
        ):
            result = recognizer.analyze(np.zeros(16_000, dtype=np.int16), tracks)

        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "ambiguous_candidates")


if __name__ == "__main__":
    unittest.main()
