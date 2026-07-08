from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.perception.semantic_vlm_server import _decode_image, _decode_text


class SemanticVlmServerTests(unittest.TestCase):
    def test_worker_text_round_trip_preserves_chinese(self) -> None:
        text = "人物：短发，微笑；动作：看电脑；环境：室内；物体：笔记本"
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self.assertEqual(_decode_text(encoded), text)

    def test_image_payload_rejects_invalid_base64(self) -> None:
        with self.assertRaisesRegex(ValueError, "Base64"):
            _decode_image({"image": "not-base64"})


if __name__ == "__main__":
    unittest.main()
