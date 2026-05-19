from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.voice.voxcpm_local import (
    VoxCpmLocalConfig,
    VoxCpmLocalSynthesizer,
    build_control_instruction,
    build_final_text,
)


class VoxCpmLocalModuleTests(unittest.TestCase):
    def test_config_resolves_model_path_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config = VoxCpmLocalConfig.from_mapping(
                {"model_path": "main/models/voxcpm/VoxCPM2", "device": "cpu"},
                project_root,
            )

        self.assertEqual(config.model_path, project_root / "main/models/voxcpm/VoxCPM2")
        self.assertEqual(config.device, "cpu")

    def test_control_instruction_absorbs_speed(self) -> None:
        self.assertEqual(build_control_instruction("年轻女性", 1.12), "年轻女性，语速稍快")
        self.assertEqual(build_control_instruction("年轻女性，语速自然", 1.12), "年轻女性，语速自然")
        self.assertEqual(build_final_text("你好。", "年轻女性"), "(年轻女性)你好。")

    def test_generation_kwargs_follow_voxcpm_clone_modes(self) -> None:
        config = VoxCpmLocalConfig(model_path=Path("D:/models/VoxCPM2"))
        synthesizer = VoxCpmLocalSynthesizer(config)

        controllable = synthesizer.build_generation_kwargs("你好。", 1.12, "ref.wav", "")
        ultimate = synthesizer.build_generation_kwargs("你好。", 1.0, "ref.wav", "参考文本。")

        self.assertEqual(controllable["reference_wav_path"], "ref.wav")
        self.assertIn("语速稍快", controllable["text"])
        self.assertEqual(ultimate["prompt_wav_path"], "ref.wav")
        self.assertEqual(ultimate["reference_wav_path"], "ref.wav")
        self.assertEqual(ultimate["prompt_text"], "参考文本。")
        self.assertNotIn("(", ultimate["text"])


if __name__ == "__main__":
    unittest.main()
