from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.perception.emotion import EmotionResult
from visual_companion_robot.perception.face_analysis import (
    FaceEnrollmentError,
    FaceProfileStore,
    LocalFaceAnalyzer,
)


class FakeEmotionRecognizer:
    def is_loaded(self) -> bool:
        return True

    def classify(self, _patch: np.ndarray) -> EmotionResult:
        return EmotionResult("happy", 0.8, {"happy": 0.8, "neutral": 0.2})


class FakeDetector:
    def __init__(self, faces: np.ndarray | None) -> None:
        self.faces = faces
        self.input_size: tuple[int, int] | None = None

    def setInputSize(self, input_size: tuple[int, int]) -> None:
        self.input_size = input_size

    def detect(self, _image: np.ndarray):  # type: ignore[no-untyped-def]
        return 1, self.faces


class FakeRecognizer:
    def __init__(self, feature: np.ndarray) -> None:
        self._feature = feature
        self.feature_calls = 0

    def alignCrop(self, image: np.ndarray, _face: np.ndarray) -> np.ndarray:
        return image[:112, :112]

    def feature(self, _aligned_face: np.ndarray) -> np.ndarray:
        self.feature_calls += 1
        return self._feature.copy()


def face(x: float, y: float, width: float, height: float) -> np.ndarray:
    return np.array(
        [x, y, width, height, x + 10, y + 10, x + 30, y + 10,
         x + 20, y + 20, x + 12, y + 32, x + 28, y + 32, 0.95],
        dtype=np.float32,
    )


class LocalFaceAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FaceProfileStore(Path(self.temp_dir.name) / "profiles.sqlite3")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def analyzer(self, faces: np.ndarray | None, feature: np.ndarray) -> LocalFaceAnalyzer:
        analyzer = LocalFaceAnalyzer(
            Path("yunet.onnx"),
            Path("sface.onnx"),
            FakeEmotionRecognizer(),  # type: ignore[arg-type]
            self.store,
            detector=FakeDetector(faces),
            recognizer=FakeRecognizer(feature),
        )
        analyzer.load()
        return analyzer

    def test_analysis_selects_focus_without_claiming_active_speaker(self) -> None:
        analyzer = self.analyzer(
            np.stack([face(10, 20, 60, 60), face(120, 50, 100, 100)]),
            np.array([1.0, 0.0, 0.0], dtype=np.float32),
        )

        result = analyzer.analyze(np.zeros((240, 320, 3), dtype=np.uint8))

        self.assertTrue(result["has_face"])
        self.assertEqual(result["focus_face_index"], 0)
        self.assertEqual(result["focus_reason"], "largest_center_face")
        self.assertEqual(result["active_speaker"]["status"], "unknown")
        self.assertEqual(result["faces"][0]["emotion"], "happy")

    def test_named_identity_is_local_embedding_match(self) -> None:
        analyzer = self.analyzer(
            np.stack([face(100, 50, 100, 100)]),
            np.array([1.0, 0.0, 0.0], dtype=np.float32),
        )
        image = np.zeros((240, 320, 3), dtype=np.uint8)

        profile = analyzer.enroll(image, "主人")
        result = analyzer.analyze(image)

        self.assertEqual(result["faces"][0]["profile_id"], profile.profile_id)
        self.assertEqual(result["faces"][0]["name"], "主人")
        self.assertEqual(len(analyzer.list_profiles()), 1)

    def test_enrollment_requires_exactly_one_face(self) -> None:
        analyzer = self.analyzer(None, np.array([1.0, 0.0], dtype=np.float32))
        with self.assertRaisesRegex(FaceEnrollmentError, "只能包含一张"):
            analyzer.enroll(np.zeros((200, 200, 3), dtype=np.uint8), "主人")

    def test_short_clip_tracking_uses_bbox_without_embedding_every_frame(self) -> None:
        recognizer = FakeRecognizer(np.array([1.0, 0.0], dtype=np.float32))
        analyzer = LocalFaceAnalyzer(
            Path("yunet.onnx"),
            Path("sface.onnx"),
            FakeEmotionRecognizer(),  # type: ignore[arg-type]
            self.store,
            detector=FakeDetector(np.stack([face(50, 40, 80, 80)])),
            recognizer=recognizer,
        )
        analyzer.load()

        tracks = analyzer.track_faces([np.zeros((200, 200, 3), dtype=np.uint8) for _ in range(16)])

        self.assertEqual(len(tracks), 1)
        self.assertEqual(len(tracks[0].crops), 16)
        self.assertLess(recognizer.feature_calls, 5)


if __name__ == "__main__":
    unittest.main()
