from __future__ import annotations

import tempfile
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.voice.voxcpm_cpp import (
    VoxCpmCppConfig,
    VoxCpmCppError,
    VoxCpmCppProcessManager,
    VoxCpmCppSynthesizer,
)


class FakeVoxCpmCppSynthesizer(VoxCpmCppSynthesizer):
    def __init__(self) -> None:
        super().__init__(VoxCpmCppConfig())
        self.calls = []

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if method == "GET" and path.startswith("/v1/voices/"):
            return 404, b"missing", "application/json"
        if method == "POST" and path == "/v1/voices":
            return 201, b"{}", "application/json"
        if method == "POST" and path == "/v1/audio/speech":
            return 200, b"RIFFxxxxWAVEdata", "audio/wav"
        raise AssertionError((method, path))


class VoxCpmCppModuleTests(unittest.TestCase):
    def test_config_rejects_non_loopback_endpoint(self) -> None:
        with self.assertRaisesRegex(VoxCpmCppError, "回环地址"):
            VoxCpmCppConfig.from_mapping({"endpoint": "http://192.168.1.9:8770"})

    def test_synthesis_registers_reference_then_uses_voice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "voice.wav"
            audio_path.write_bytes(b"RIFFxxxxWAVEref")
            synthesizer = FakeVoxCpmCppSynthesizer()

            audio, content_type = synthesizer.synthesize(
                "你好。", 1.1, "soft_girl", str(audio_path), "参考文本。"
            )

        self.assertEqual(audio, b"RIFFxxxxWAVEdata")
        self.assertEqual(content_type, "audio/wav")
        self.assertEqual([call[:2] for call in synthesizer.calls], [
            ("GET", "/v1/voices/soft_girl"),
            ("POST", "/v1/voices"),
            ("POST", "/v1/audio/speech"),
        ])
        voice_body = synthesizer.calls[1][2]["body"]
        self.assertIn(b'name="id"', voice_body)
        self.assertIn("参考文本。".encode("utf-8"), voice_body)
        speech_body = synthesizer.calls[2][2]["body"]
        self.assertIn(b'"voice": "soft_girl"', speech_body)

    def test_prepare_checks_board_files_without_starting_server(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = root / "voxcpm-server"
            model = root / "model.gguf"
            executable.write_bytes(b"binary")
            executable.chmod(0o755)
            model.write_bytes(b"model")
            synthesizer = VoxCpmCppSynthesizer(VoxCpmCppConfig(
                auto_start=True,
                executable_path=str(executable),
                model_path=str(model),
                voice_dir=str(root / "voices"),
            ))
            with patch("visual_companion_robot.voice.voxcpm_cpp.subprocess.Popen") as popen:
                status = synthesizer.prepare()

        self.assertTrue(status["ok"])
        self.assertEqual(status["state"], "installed")
        popen.assert_not_called()

    def test_managed_process_is_released_after_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = root / "voxcpm-server"
            model = root / "model.gguf"
            executable.write_bytes(b"binary")
            model.write_bytes(b"model")
            config = VoxCpmCppConfig(
                executable_path=str(executable),
                model_path=str(model),
                voice_dir=str(root / "voices"),
            )
            manager = VoxCpmCppProcessManager(config)
            process = Mock()
            process.poll.return_value = None
            with (
                patch.object(manager, "_healthy", side_effect=[False, True]),
                patch("visual_companion_robot.voice.voxcpm_cpp.subprocess.Popen", return_value=process),
                patch.dict(os.environ, {"VOXCPM_CPP_LOG": str(root / "voxcpm.log")}),
            ):
                with manager.session():
                    pass

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=10)


if __name__ == "__main__":
    unittest.main()
