from __future__ import annotations

import io
import json
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import numpy as np

from main.scripts import live2d_control_server as control_server
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
    sanitize_vision_context,
    select_reference_config,
    select_voice_config,
    synthesize_sherpa_onnx,
    ControlHandler,
)
from visual_companion_robot.perception.offline_asr_service import OfflineAsrResult


class VoxcpmControlServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ControlHandler)
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def request_json(self, method: str, path: str, body: str = "") -> tuple[int, dict]:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json"} if body else {}
        connection.request(method, path, body=body.encode("utf-8"), headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, payload

    def request_bytes(self, path: str, body: bytes, content_type: str) -> tuple[int, dict]:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request("POST", path, body=body, headers={"Content-Type": content_type})
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, payload

    def request_with_origin(self, origin: str) -> tuple[int, dict, str | None]:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request("GET", "/health", headers={"Origin": origin})
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        allowed_origin = response.getheader("Access-Control-Allow-Origin")
        connection.close()
        return response.status, payload, allowed_origin

    def test_http_routes_expose_health_voices_and_validation(self) -> None:
        status, health = self.request_json("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])

        status, voices = self.request_json("GET", "/voices")
        self.assertEqual(status, 200)
        self.assertIn(voices["active"], voices["models"])

        status, asr_health = self.request_json("GET", "/asr-health")
        self.assertEqual(status, 200)
        self.assertEqual(asr_health["backend"], "sherpa-onnx-sensevoice")

        status, error = self.request_json("POST", "/chat", '{"text":""}')
        self.assertEqual(status, 400)
        self.assertIn("text", error["error"])

    def test_read_only_routes_handle_concurrent_requests(self) -> None:
        paths = ["/health", "/voices", "/asr-health"] * 8
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda path: self.request_json("GET", path), paths))

        self.assertTrue(all(status == 200 for status, _ in results))

    def test_http_rejects_invalid_or_oversized_json_before_dispatch(self) -> None:
        for body in ("[]", "{broken"):
            status, error = self.request_json("POST", "/chat", body)
            self.assertEqual(status, 400)
            self.assertIn("JSON", error["error"])

        status, error = self.request_json("POST", "/tts", '{"text":"测试","rate":"fast"}')
        self.assertEqual(status, 400)
        self.assertIn("rate", error["error"])

        status, error = self.request_json("POST", "/chat", '{"text":"测试","rate":"fast"}')
        self.assertEqual(status, 400)
        self.assertIn("rate", error["error"])

        oversized = json.dumps({"text": "x" * (128 * 1024)}, ensure_ascii=False)
        status, error = self.request_json("POST", "/chat", oversized)
        self.assertEqual(status, 413)
        self.assertIn("128 KiB", error["error"])

        for invalid_rate in ('"NaN"', '"Infinity"'):
            status, error = self.request_json("POST", "/tts", f'{{"text":"测试","rate":{invalid_rate}}}')
            self.assertEqual(status, 400)
            self.assertIn("有限", error["error"])

    def test_cors_only_allows_local_browser_origins(self) -> None:
        status, payload, allowed_origin = self.request_with_origin("https://malicious.example")
        self.assertEqual(status, 403)
        self.assertIn("Origin", payload["error"])
        self.assertIsNone(allowed_origin)

        local_origin = "http://127.0.0.1:5174"
        status, payload, allowed_origin = self.request_with_origin(local_origin)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(allowed_origin, local_origin)

    def test_asr_route_accepts_pcm16_and_rejects_wrong_content_type(self) -> None:
        result = OfflineAsrResult("你好", True, 0.5, 600)
        pcm = b"\x00\x00" * (16_000 * 600 // 1000)
        with patch.object(control_server.ASR_SERVICE, "transcribe_pcm16", return_value=result) as transcribe:
            status, payload = self.request_bytes("/asr", pcm, "audio/pcm; rate=16000")

        self.assertEqual(status, 200)
        self.assertEqual(payload["text"], "你好")
        transcribe.assert_called_once_with(pcm)

        status, error = self.request_bytes("/asr", pcm, "application/octet-stream")
        self.assertEqual(status, 400)
        self.assertIn("audio/pcm", error["error"])

        status, error = self.request_bytes("/asr", pcm, "audio/pcm; rate=8000")
        self.assertEqual(status, 400)
        self.assertIn("16000", error["error"])

        with patch.object(control_server.ASR_SERVICE, "transcribe_pcm16", side_effect=RuntimeError("model unavailable")):
            status, error = self.request_bytes("/asr", pcm, "audio/pcm; rate=16000")
        self.assertEqual(status, 503)
        self.assertIn("model unavailable", error["error"])

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

    def test_sherpa_runtime_config_does_not_require_reference_audio(self) -> None:
        runtime_config = build_runtime_voice_config(
            {"backend": "sherpa_onnx", "speaker_id": 5},
            "missing-reference",
            None,
        )

        self.assertEqual(runtime_config, {"backend": "sherpa_onnx", "speaker_id": 5})

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

    def test_sherpa_voice_is_default_and_checked_locally(self) -> None:
        selected, voice_config = select_voice_config("")
        health = probe_voxcpm_backend(voice_config)

        self.assertEqual(selected, "sherpa_vits")
        self.assertEqual(health["backend"], "sherpa_onnx")
        self.assertIn("model_path", health)

    def test_sherpa_synthesis_returns_valid_wav(self) -> None:
        samples = np.array([0.0, 0.25, -0.25], dtype=np.float32)
        with (
            patch.object(control_server.SHERPA_TTS_ENGINE, "load") as load,
            patch.object(control_server.SHERPA_TTS_ENGINE, "synthesize", return_value=(samples, 8000)) as synthesize,
        ):
            audio, content_type = synthesize_sherpa_onnx("你好", 1.1, {"speaker_id": 3})

        load.assert_called_once_with()
        synthesize.assert_called_once_with("你好", sid=3, speed=1.1)
        self.assertEqual(content_type, "audio/wav")
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 8000)
            self.assertEqual(wav_file.getnframes(), 3)

    def test_sherpa_runtime_loads_model_and_releases_voxcpm(self) -> None:
        status = {"ok": True, "backend": "sherpa_onnx", "loaded": True, "model_path": "model"}
        with (
            patch("main.scripts.live2d_control_server.release_cached_models", return_value=1) as release_cache,
            patch.object(control_server.SHERPA_TTS_ENGINE, "load") as load,
            patch.object(control_server.SHERPA_TTS_ENGINE, "environment_status", return_value=status),
        ):
            result = activate_tts_runtime("sherpa_vits")

        release_cache.assert_called_once_with()
        load.assert_called_once_with()
        self.assertTrue(result["ok"])
        self.assertEqual(result["voice"], "sherpa_vits")
        self.assertEqual(result["action"], "prepare_local_model")

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

    def test_sanitize_vision_context_keeps_small_trusted_shape(self) -> None:
        context = sanitize_vision_context(
            {
                "status": "running-with-extra-long-status-that-should-be-trimmed",
                "hasFace": True,
                "emotion": "happy",
                "emotionSource": "ferplus",
                "emotionConfidence": 1.5,
                "fullScores": {"happy": 0.9, "sad": -1, "unknown": 9},
                "headPose": {"angleX": 99, "angleY": "-99", "bodyAngleZ": 12.34},
                "mouth": {"smile": 0.4567, "open": 8},
                "eyes": {"open": "0.3219"},
            }
        )

        self.assertTrue(context["enabled"])
        self.assertTrue(context["has_face"])
        self.assertEqual(context["emotion"], "happy")
        self.assertEqual(context["emotion_source"], "ferplus")
        self.assertEqual(context["emotion_confidence"], 1.0)
        self.assertEqual(context["emotion_scores"], {"happy": 0.9, "sad": 0.0})
        self.assertEqual(context["head_pose"]["angle_x"], 45.0)
        self.assertEqual(context["head_pose"]["angle_y"], -45.0)
        self.assertEqual(context["head_pose"]["body_angle_z"], 12.3)
        self.assertEqual(context["mouth"]["smile"], 0.457)
        self.assertEqual(context["mouth"]["open"], 1.0)
        self.assertEqual(context["eyes"]["open"], 0.322)

    def test_sanitize_vision_context_marks_missing_payload_disabled(self) -> None:
        self.assertEqual(sanitize_vision_context(None), {"enabled": False})


if __name__ == "__main__":
    unittest.main()
