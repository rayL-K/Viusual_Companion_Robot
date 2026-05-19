from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from main.scripts.live2d_control_server import (
    activate_tts_runtime,
    build_gradio_file_data,
    build_runtime_voice_config,
    build_voxcpm_gradio_payload,
    build_voxcpm_hf_space_payload,
    detect_audio_content_type,
    parse_gradio_sse_data,
    probe_voxcpm_backend,
    resolve_voxcpm_base_url,
    select_reference_config,
    select_voice_config,
)


class VoxcpmControlServerTests(unittest.TestCase):
    def test_detect_audio_content_type_uses_file_header(self) -> None:
        self.assertEqual(detect_audio_content_type(b"RIFFxxxxWAVEdata", "application/octet-stream"), "audio/wav")
        self.assertEqual(detect_audio_content_type(b"\xff\xfb\x90\x64", "application/octet-stream"), "audio/mpeg")
        self.assertEqual(detect_audio_content_type(b"unknown", "audio/ogg"), "audio/ogg")

    def test_runtime_voice_config_uses_selected_reference(self) -> None:
        reference_id, reference_config = select_reference_config("soft_girl")
        runtime_config = build_runtime_voice_config(
            {"backend": "voxcpm_hf_space"},
            reference_id,
            "用户编辑后的参考文本。",
        )

        self.assertEqual(reference_id, "soft_girl")
        self.assertEqual(runtime_config["ref_audio_path"], reference_config["audio_path"])
        self.assertEqual(runtime_config["prompt_text"], "用户编辑后的参考文本。")

    def test_project_local_runtime_config_keeps_selected_reference(self) -> None:
        _, voice_config = select_voice_config("voxcpm_local")
        reference_id, reference_config = select_reference_config("soft_girl")

        runtime_config = build_runtime_voice_config(
            voice_config,
            reference_id,
            "本地推理也使用用户编辑后的参考文本。",
        )

        self.assertEqual(runtime_config["backend"], "voxcpm_project_local")
        self.assertEqual(runtime_config["ref_audio_path"], reference_config["audio_path"])
        self.assertEqual(runtime_config["prompt_text"], "本地推理也使用用户编辑后的参考文本。")

    def test_voxcpm_hf_space_payload_uses_gradio_queue_shape(self) -> None:
        payload = build_voxcpm_hf_space_payload(
            "你好，开始测试。",
            1.12,
            {
                "control_instruction": "年轻女性，温柔甜美，语气自然",
                "cfg_value": 2.0,
                "do_normalize": True,
                "denoise": False,
            },
        )

        self.assertEqual(payload["data"][0], "你好，开始测试。")
        self.assertIn("语速稍快", payload["data"][1])
        self.assertIsNone(payload["data"][2])
        self.assertFalse(payload["data"][3])
        self.assertEqual(payload["data"][4], "")
        self.assertEqual(payload["data"][5], 2.0)
        self.assertTrue(payload["data"][6])
        self.assertFalse(payload["data"][7])

    def test_voxcpm_hf_space_payload_can_use_reference_audio_prompt(self) -> None:
        reference_audio = build_gradio_file_data("/tmp/gradio/ref.mp3", Path("ref.mp3"))
        payload = build_voxcpm_hf_space_payload(
            "请用参考音色读这句话。",
            1.0,
            {
                "control_instruction": "年轻女性，温柔甜美",
                "prompt_text": "这是参考音频的文本。",
            },
            reference_audio=reference_audio,
        )

        self.assertEqual(payload["data"][1], "")
        self.assertEqual(payload["data"][2]["path"], "/tmp/gradio/ref.mp3")
        self.assertTrue(payload["data"][3])
        self.assertEqual(payload["data"][4], "这是参考音频的文本。")

    def test_local_voxcpm_backend_uses_local_endpoint(self) -> None:
        self.assertEqual(
            resolve_voxcpm_base_url({"backend": "voxcpm_local_gradio", "endpoint": "http://127.0.0.1:7860/"}),
            "http://127.0.0.1:7860",
        )

    def test_local_gradio_payload_includes_inference_steps(self) -> None:
        payload = build_voxcpm_gradio_payload(
            "本地推理测试。",
            1.0,
            {
                "backend": "voxcpm_local_gradio",
                "control_instruction": "年轻女性，温柔甜美",
                "cfg_value": 2.0,
                "do_normalize": True,
                "denoise": False,
                "inference_timesteps": 10,
            },
        )

        self.assertEqual(payload["data"][8], 10)

    def test_project_local_voice_is_checked_without_http_endpoint(self) -> None:
        _, voice_config = select_voice_config("voxcpm_local")
        health = probe_voxcpm_backend(voice_config)

        self.assertEqual(health["backend"], "voxcpm_project_local")
        self.assertIn("model_path", health)

    def test_cloud_runtime_releases_project_local_model_cache(self) -> None:
        with patch("main.scripts.live2d_control_server.release_cached_models", return_value=2) as release_cache:
            result = activate_tts_runtime("voxcpm_hf_space_test")

        release_cache.assert_called_once_with()
        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "voxcpm_hf_space")
        self.assertEqual(result["action"], "release_local_model")
        self.assertEqual(result["released_models"], 2)

    def test_project_local_runtime_prepares_model_cache(self) -> None:
        with patch("main.scripts.live2d_control_server.VoxCpmLocalSynthesizer.prepare") as prepare:
            prepare.return_value = {"ok": True, "backend": "voxcpm_project_local", "loaded": True}
            result = activate_tts_runtime("voxcpm_local")

        prepare.assert_called_once_with()
        self.assertTrue(result["ok"])
        self.assertEqual(result["voice"], "voxcpm_local")
        self.assertEqual(result["action"], "prepare_local_model")

    def test_gradio_sse_parser_prefers_complete_event(self) -> None:
        raw_text = "\n\n".join(
            [
                "event: generating\ndata: null",
                "event: complete\ndata: [{\"url\":\"https://example.com/audio.mp3\"}]",
            ]
        )

        result = parse_gradio_sse_data(raw_text)

        self.assertEqual(result[0]["url"], "https://example.com/audio.mp3")


if __name__ == "__main__":
    unittest.main()
