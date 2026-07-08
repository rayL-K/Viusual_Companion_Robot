from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.perception.pose import classify_pose


def skeleton() -> list[tuple[float, float, float]]:
    points = [(50.0, 20.0, 0.9)] * 17
    points[5], points[6] = (40, 60, 0.9), (60, 60, 0.9)
    points[9], points[10] = (40, 90, 0.9), (60, 90, 0.9)
    points[11], points[12] = (43, 110, 0.9), (57, 110, 0.9)
    points[13], points[14] = (43, 160, 0.9), (57, 160, 0.9)
    points[15], points[16] = (43, 210, 0.9), (57, 210, 0.9)
    return points


class PoseSemanticsTests(unittest.TestCase):
    def test_raised_hand_and_standing_are_reported(self) -> None:
        points = skeleton()
        points[9] = (38, 30, 0.9)

        actions, state = classify_pose(tuple(points), (20, 10, 80, 220))

        self.assertIn("left_hand_raised", actions)
        self.assertEqual(state, "standing")

    def test_low_confidence_wrist_does_not_claim_action(self) -> None:
        points = skeleton()
        points[9] = (38, 20, 0.1)

        actions, _ = classify_pose(tuple(points), (20, 10, 80, 220))

        self.assertNotIn("left_hand_raised", actions)

    def test_horizontal_thigh_is_classified_as_sitting(self) -> None:
        points = skeleton()
        points[13], points[14] = (10, 118, 0.9), (90, 118, 0.9)

        _, state = classify_pose(tuple(points), (5, 10, 95, 180))

        self.assertEqual(state, "sitting")


if __name__ == "__main__":
    unittest.main()
