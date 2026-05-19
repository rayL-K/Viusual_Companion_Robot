"""嘴型同步测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.ui.live2d.mouth_sync import (
    VISEME_SHAPES,
    build_mouth_sync_frames,
    build_visual_mouth_test_sequence,
    summarize_viseme_coverage,
    validate_mouth_shape_config,
)


class MouthSyncTest(unittest.TestCase):
    """验证固定嘴型测试序列的覆盖能力。"""

    def test_visual_sequence_covers_core_visemes(self) -> None:
        samples = build_visual_mouth_test_sequence()
        coverage = summarize_viseme_coverage(samples)

        for viseme in VISEME_SHAPES:
            self.assertIn(viseme, coverage)
            self.assertGreater(len(coverage[viseme]), 0)

    def test_visual_sequence_contains_mandarin_and_english_tokens(self) -> None:
        tokens = {sample.token for sample in build_visual_mouth_test_sequence()}

        for token in ("b", "p", "m", "f", "zh", "ch", "sh", "ü", "ang", "eng", "AA", "AE", "TH", "DH"):
            self.assertIn(token, tokens)

    def test_frames_follow_sample_timeline(self) -> None:
        samples = build_visual_mouth_test_sequence(duration_ms=200)
        frames = build_mouth_sync_frames(samples)

        self.assertEqual(len(frames), len(samples))
        self.assertEqual(frames[0].timestamp_sec, 0.0)
        self.assertAlmostEqual(frames[1].timestamp_sec, 0.2)
        self.assertGreater(max(frame.mouth_open for frame in frames), 0.7)

    def test_config_is_valid_and_contains_audio_cues(self) -> None:
        errors = validate_mouth_shape_config()
        samples = build_visual_mouth_test_sequence()

        self.assertEqual(errors, [])
        self.assertTrue(any(sample.audio.mode != "silence" for sample in samples))
        self.assertTrue(all(0.0 <= sample.shape.mouth_open <= 1.0 for sample in samples))
        self.assertTrue(all(0.0 <= sample.shape.mouth_width <= 1.0 for sample in samples))


if __name__ == "__main__":
    unittest.main()
