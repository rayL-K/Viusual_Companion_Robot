"""配置加载与 Live2D 资源加载的基础测试。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.runtime.config import ConfigError, load_app_config
from visual_companion_robot.ui.live2d.avatar import Live2DAssetError, load_live2d_avatar


class ConfigLoadingTest(unittest.TestCase):
    """验证应用配置能被稳定读取。"""

    def test_default_config_loads_live2d_paths(self) -> None:
        config = load_app_config()

        self.assertEqual(config.app_name, "visual_companion_robot")
        self.assertEqual(config.mode, "development")
        self.assertTrue(config.live2d_display.enabled)
        self.assertEqual(config.live2d_display.model_name, "Strawberry_Rabbit")
        self.assertTrue(config.live2d_display.model_path.is_file())
        self.assertTrue(config.live2d_display.manifest_path.is_file())

    def test_config_rejects_path_outside_main(self) -> None:
        config_text = """
app:
  name: visual_companion_robot
  mode: development
runtime:
  display: ":0"
  log_level: INFO
modules:
  live2d_display:
    enabled: true
    model_name: Strawberry_Rabbit
    model_path: ../README.md
    manifest_path: assets/live2d/Strawberry_Rabbit/manifest.json
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text(config_text, encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_app_config(config_path)


class Live2DAvatarLoadingTest(unittest.TestCase):
    """验证 Live2D manifest 能被加载成稳定资源对象。"""

    def test_manifest_loads_named_assets(self) -> None:
        config = load_app_config()
        avatar = load_live2d_avatar(
            config.live2d_display.manifest_path,
            expected_name=config.live2d_display.model_name,
            expected_model3_path=config.live2d_display.model_path,
        )

        self.assertEqual(avatar.name, "Strawberry_Rabbit")
        self.assertTrue(avatar.model3_path.is_file())
        self.assertEqual(len(avatar.expressions), 25)
        self.assertEqual(len(avatar.motions), 4)
        self.assertTrue(avatar.expression_path("heart").is_file())
        self.assertTrue(avatar.motion_path("scene1").is_file())

    def test_manifest_rejects_asset_outside_model_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "name": "Broken",
                        "model3": "../escape.model3.json",
                        "expressions": {"heart": "heart.exp3.json"},
                        "motions": {"idle": "idle.motion3.json"},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(Live2DAssetError):
                load_live2d_avatar(manifest_path)

    def test_unknown_expression_reports_clear_error(self) -> None:
        config = load_app_config()
        avatar = load_live2d_avatar(config.live2d_display.manifest_path)

        with self.assertRaises(Live2DAssetError):
            avatar.expression_path("not_exists")


if __name__ == "__main__":
    unittest.main()
