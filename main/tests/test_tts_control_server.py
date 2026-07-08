from __future__ import annotations

import io
import base64
import json
import os
import tempfile
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
    build_direct_vision_control_plan,
    build_runtime_voice_config,
    dispatch_realtime_message,
    probe_voxcpm_backend,
    resolve_live2d_asset,
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

    def request_json(
        self,
        method: str,
        path: str,
        body: str = "",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json"} if body else {}
        headers.update(extra_headers or {})
        connection.request(method, path, body=body.encode("utf-8"), headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, payload

    def request_raw(self, path: str) -> tuple[int, bytes, str | None]:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request("GET", path)
        response = connection.getresponse()
        payload = response.read()
        content_type = response.getheader("Content-Type")
        connection.close()
        return response.status, payload, content_type

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
        serialized_voices = json.dumps(voices)
        self.assertNotIn("model_path", serialized_voices)
        self.assertNotIn("audio_path", serialized_voices)
        self.assertNotIn("voxcpm_hf_space", {model["backend"] for model in voices["models"].values()})

        status, asr_health = self.request_json("GET", "/asr-health")
        self.assertEqual(status, 200)
        self.assertEqual(asr_health["backend"], "sherpa-onnx-sensevoice")

        status, error = self.request_json("POST", "/chat", '{"text":""}')
        self.assertEqual(status, 400)
        self.assertIn("text", error["error"])

    def test_live2d_assets_are_served_with_path_boundary(self) -> None:
        asset = resolve_live2d_asset("Strawberry_Rabbit/manifest.json")
        self.assertEqual(asset.name, "manifest.json")
        with self.assertRaisesRegex(FileNotFoundError, "越界"):
            resolve_live2d_asset("../config/app.yaml")

        status, payload, content_type = self.request_raw("/live2d/Strawberry_Rabbit/manifest.json")
        self.assertEqual(status, 200)
        self.assertTrue(payload.startswith(b"{"))
        self.assertIn("json", content_type or "")

        status, payload, content_type = self.request_raw("/live2d/../config/app.yaml")
        self.assertEqual(status, 404)
        self.assertIn(b"error", payload)
        self.assertIn("json", content_type or "")

    def test_post_routes_require_device_token_when_configured(self) -> None:
        with patch.dict(os.environ, {"VISUAL_COMPANION_DEVICE_TOKEN": "test-device-token"}):
            status, payload = self.request_json("GET", "/reference-audio?id=soft_girl")
            self.assertEqual(status, 401)
            self.assertIn("令牌", payload["error"])

            status, payload = self.request_json("POST", "/chat", '{"text":"hello"}')
            self.assertEqual(status, 401)
            self.assertIn("令牌", payload["error"])

            status, payload = self.request_json(
                "POST",
                "/chat",
                '{"text":""}',
                extra_headers={"X-Device-Token": "test-device-token"},
            )
            self.assertEqual(status, 400)
            self.assertIn("text", payload["error"])

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

    def test_chat_visual_question_bypasses_deepseek_and_uses_current_vision(self) -> None:
        body = json.dumps(
            {
                "text": "你看到的画面是什么样子？",
                "vision": {
                    "enabled": True,
                    "status": "running",
                    "sceneCaption": "画面中有1人、1个toothbrush",
                    "semanticCaption": "人物：青年男性；外观和表情：戴眼镜，神情专注；环境：室内，背景模糊",
                    "personCount": 1,
                    "objectsDetected": ["person", "toothbrush"],
                },
            },
            ensure_ascii=False,
        )

        with patch("main.scripts.live2d_control_server.get_llm_client") as get_llm_client:
            get_llm_client.side_effect = AssertionError("视觉直答不应调用 DeepSeek")
            status, payload = self.request_json("POST", "/chat", body)

        self.assertEqual(status, 200)
        self.assertIn("青年男性", payload["text"])
        self.assertIn("牙刷", payload["text"])
        self.assertNotIn("蓝天", payload["text"])

    def test_chat_short_followup_uses_llm_with_recent_turn(self) -> None:
        class CapturingClient:
            def __init__(self) -> None:
                self.contexts = []

            def generate_live2d_control(self, context):
                self.contexts.append(context)
                if "为什么" in context.user_prompt:
                    reply = "因为我在接着刚才开心的话题认真回答你。"
                    emotion = "thinking"
                    expression = "question"
                    motion = "captain"
                else:
                    reply = "开心呀，能和你一起聊天、一起测试，我就会很开心。"
                    emotion = "happy"
                    expression = "heart"
                    motion = "scene1"
                return control_server.Live2DControlPlan(
                    text=reply,
                    emotion=emotion,
                    expression=expression,
                    motion=motion,
                    speech=control_server.SpeechControl(rate=1.08, pitch=1.15),
                    parameters={"ParamMouthForm": 0.2},
                )

        fake_client = CapturingClient()
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.object(control_server, "MEMORY_DB_PATH", Path(temporary_directory) / "memory.sqlite3"),
            patch("main.scripts.live2d_control_server.get_llm_client") as get_llm_client,
        ):
            get_llm_client.return_value = fake_client

            status, happy_payload = self.request_json("POST", "/chat", '{"text":"你开心吗？"}')
            status_followup, followup_payload = self.request_json("POST", "/chat", '{"text":"为什么？"}')

        self.assertEqual(status, 200)
        self.assertIn("开心", happy_payload["text"])
        self.assertEqual(status_followup, 200)
        self.assertIn("因为", followup_payload["text"])
        self.assertIn("开心", followup_payload["text"])
        self.assertNotIn("为什么这么问", followup_payload["text"])
        self.assertGreaterEqual(len(fake_client.contexts), 2)
        followup_memory = json.dumps(fake_client.contexts[-1].memory_context, ensure_ascii=False)
        self.assertIn("你开心吗", followup_memory)
        self.assertIn("开心呀", followup_memory)

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

        wechat_origin = "https://servicewechat.com"
        status, payload, allowed_origin = self.request_with_origin(wechat_origin)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(allowed_origin, wechat_origin)

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

    def test_emotion_routes_are_exposed_through_the_control_gateway(self) -> None:
        health = json.dumps({"ok": True, "backend": "ferplus-onnx"}).encode("utf-8")
        result = json.dumps({"has_face": False, "emotion": "neutral"}).encode("utf-8")
        with patch.object(
            control_server,
            "proxy_emotion_request",
            side_effect=[
                (200, health, "application/json"),
                (200, result, "application/json"),
            ],
        ) as proxy:
            status, payload = self.request_json("GET", "/emotion-health")
            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            status, payload = self.request_json("POST", "/emotion", '{"image":"ZmFrZQ=="}')
            self.assertEqual(status, 200)
            self.assertFalse(payload["has_face"])

        self.assertEqual(proxy.call_args_list[0].args[:2], ("GET", "/health"))
        self.assertEqual(proxy.call_args_list[1].args[:2], ("POST", "/emotion"))

    def test_vision_routes_require_unified_local_result(self) -> None:
        health = {"ok": True, "backend": "elf2-local-yolo-pose-yunet-sface-ferplus"}
        result = {
            "ok": True,
            "scene_caption": "画面中有1人",
            "emotion": "happy",
            "has_face": True,
        }
        with (
            patch.object(control_server.VISION_SERVICE, "health", return_value=health) as health_call,
            patch.object(control_server.VISION_SERVICE, "analyze", return_value=result) as analyze,
        ):
            status, payload = self.request_json("GET", "/vision-health")
            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            status, payload = self.request_json("POST", "/vision", '{"image":"ZmFrZQ=="}')
            self.assertEqual(status, 200)
            self.assertEqual(payload["emotion"], "happy")

        health_call.assert_called_once_with()
        analyze.assert_called_once_with("ZmFrZQ==")

    def test_realtime_dispatch_keeps_vision_and_asr_on_board(self) -> None:
        vision_result = {"ok": True, "backend": "elf2-local-yolo-pose-yunet-sface-ferplus"}
        asr_result = OfflineAsrResult("实时识别", True, 0.7, 480)
        pcm = b"\x01\x00" * 3200
        with (
            patch.object(control_server.VISION_SERVICE, "analyze", return_value=vision_result) as analyze,
            patch.object(control_server.ASR_SERVICE, "transcribe_pcm16", return_value=asr_result) as transcribe,
        ):
            vision = dispatch_realtime_message({"id": "v1", "type": "vision", "image": "ZmFrZQ=="})
            asr = dispatch_realtime_message({
                "id": "a1",
                "type": "asr",
                "sample_rate": 16000,
                "audio_pcm_base64": base64.b64encode(pcm).decode("ascii"),
            })

        self.assertTrue(vision["ok"])
        self.assertEqual(vision["data"], vision_result)
        self.assertEqual(asr["data"]["text"], "实时识别")
        analyze.assert_called_once_with("ZmFrZQ==")
        transcribe.assert_called_once_with(pcm)

        invalid = dispatch_realtime_message({"id": "a2", "type": "asr", "sample_rate": 8000})
        self.assertFalse(invalid["ok"])
        self.assertIn("16000", invalid["error"])

    def test_realtime_route_requires_websocket_upgrade(self) -> None:
        status, payload = self.request_json("GET", "/realtime")
        self.assertEqual(status, 426)
        self.assertIn("WebSocket", payload["error"])

    def test_runtime_voice_config_uses_selected_reference(self) -> None:
        reference_id, reference_config = select_reference_config("soft_girl")
        runtime_config = build_runtime_voice_config(
            {"backend": "voxcpm_cpp_local"},
            reference_id,
            "用户编辑后的参考文本。",
        )

        self.assertEqual(reference_id, "soft_girl")
        self.assertEqual(runtime_config["ref_audio_path"], reference_config["audio_path"])
        self.assertEqual(runtime_config["prompt_text"], "用户编辑后的参考文本。")
        self.assertEqual(runtime_config["reference_id"], "soft_girl")

    def test_sherpa_runtime_config_does_not_require_reference_audio(self) -> None:
        runtime_config = build_runtime_voice_config(
            {"backend": "sherpa_onnx", "speaker_id": 5},
            "missing-reference",
            None,
        )

        self.assertEqual(runtime_config, {"backend": "sherpa_onnx", "speaker_id": 5})

    def test_cpp_voice_is_configured_for_board_loopback(self) -> None:
        selected, voice_config = select_voice_config("voxcpm_board")
        self.assertEqual(selected, "voxcpm_board")
        self.assertEqual(voice_config["backend"], "voxcpm_cpp_local")
        self.assertEqual(voice_config["endpoint"], "http://127.0.0.1:8770")

    def test_cpp_runtime_does_not_release_matcha_when_health_fails(self) -> None:
        with (
            patch("main.scripts.live2d_control_server.VoxCpmCppSynthesizer.prepare", return_value={"ok": False, "message": "offline"}),
            patch.object(control_server.SHERPA_TTS_ENGINE, "release") as release_sherpa,
        ):
            result = activate_tts_runtime("voxcpm_board")

        self.assertFalse(result["ok"])
        release_sherpa.assert_not_called()

    def test_cpp_runtime_releases_other_tts_only_after_prepare_succeeds(self) -> None:
        with (
            patch("main.scripts.live2d_control_server.VoxCpmCppSynthesizer.prepare", return_value={"ok": True, "message": "ready"}),
            patch.object(control_server.SHERPA_TTS_ENGINE, "release", return_value=True),
        ):
            result = activate_tts_runtime("voxcpm_board")

        self.assertTrue(result["ok"])
        self.assertTrue(result["released_sherpa"])

    def test_matcha_voice_is_default_and_checked_locally(self) -> None:
        selected, voice_config = select_voice_config("")
        health = probe_voxcpm_backend(voice_config)

        self.assertEqual(selected, "matcha_baker")
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

    def test_sherpa_runtime_loads_model(self) -> None:
        status = {"ok": True, "backend": "sherpa_onnx", "loaded": True, "model_path": "model"}
        with (
            patch.object(control_server.SHERPA_TTS_ENGINE, "load") as load,
            patch.object(control_server.SHERPA_TTS_ENGINE, "environment_status", return_value=status),
        ):
            result = activate_tts_runtime("matcha_baker")

        load.assert_called_once_with()
        self.assertTrue(result["ok"])
        self.assertEqual(result["voice"], "matcha_baker")
        self.assertEqual(result["action"], "prepare_local_model")

    def test_public_cloud_voice_is_not_selectable(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "未配置"):
            activate_tts_runtime("voxcpm_hf_space_test")

    def test_sanitize_vision_context_keeps_small_trusted_shape(self) -> None:
        context = sanitize_vision_context(
            {
                "status": "running-with-extra-long-status-that-should-be-trimmed",
                "hasFace": True,
                "timestamp": "2026-07-05T06:44:00+00:00",
                "sceneCaption": "画面中有1人、1台笔记本电脑",
                "semanticCaption": "一名戴眼镜的人坐在书桌前，背景有显示器和窗户。",
                "semanticStatus": "ready",
                "personActivity": "人物可能正在使用电脑",
                "personCount": 1,
                "objectsDetected": ["person", "laptop"],
                "emotion": "happy",
                "emotionConfidence": 1.5,
                "fullScores": {"happy": 0.9, "sad": -1, "unknown": 9},
                "focusPerson": {
                    "name": "主人",
                    "profileId": "profile-1",
                    "identitySimilarity": 0.91,
                },
                "activeSpeaker": {
                    "status": "confirmed",
                    "reason": "audio_visual_consistency",
                    "name": "主人",
                    "profileId": "profile-1",
                    "confidence": 0.87,
                },
            }
        )

        self.assertTrue(context["enabled"])
        self.assertTrue(context["has_face"])
        self.assertEqual(context["emotion"], "happy")
        self.assertEqual(context["emotion_source"], "ferplus-onnx")
        self.assertEqual(context["emotion_confidence"], 1.0)
        self.assertEqual(context["emotion_scores"], {"happy": 0.9, "sad": 0.0})
        self.assertEqual(context["scene_caption"], "画面中有1人、1台笔记本电脑")
        self.assertEqual(context["semantic_caption"], "一名戴眼镜的人坐在书桌前，背景有显示器和窗户。")
        self.assertEqual(context["semantic_status"], "ready")
        self.assertEqual(context["person_activity"], "人物可能正在使用电脑")
        self.assertEqual(context["person_count"], 1)
        self.assertEqual(context["objects_detected"], ["person", "laptop"])
        self.assertEqual(
            context["focus_person"],
            {"name": "主人", "profile_id": "profile-1", "identity_similarity": 0.91},
        )
        self.assertEqual(
            context["active_speaker"],
            {
                "status": "confirmed",
                "reason": "audio_visual_consistency",
                "name": "主人",
                "profile_id": "profile-1",
                "confidence": 0.87,
            },
        )

    def test_sanitize_vision_context_marks_missing_payload_disabled(self) -> None:
        self.assertEqual(sanitize_vision_context(None), {"enabled": False})
        self.assertEqual(sanitize_vision_context({"enabled": False}), {"enabled": False})

    def test_visual_question_uses_board_context_without_llm(self) -> None:
        context = sanitize_vision_context(
            {
                "enabled": True,
                "status": "running",
                "sceneCaption": "画面中有1人、1个toothbrush",
                "semanticCaption": (
                    "人物：青年男性；外观和表情：戴眼镜，神情专注；"
                    "动作：侧头凝视；环境：室内，背景模糊；物体：耳机"
                ),
                "personActivity": "侧头凝视",
                "personCount": 1,
                "objectsDetected": ["person", "toothbrush", "headphones"],
            }
        )

        plan = build_direct_vision_control_plan(
            "你看到的画面是什么样子？",
            context,
            expressions=["heart", "question"],
            motions=["scene1", "captain"],
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("青年男性", plan.text)
        self.assertIn("戴眼镜", plan.text)
        self.assertIn("室内", plan.text)
        self.assertIn("牙刷", plan.text)
        self.assertNotIn("person", plan.text)
        self.assertNotIn("检测到的物体包括", plan.text)
        self.assertNotIn("蓝天", plan.text)
        self.assertEqual(plan.expression, "question")
        self.assertEqual(plan.motion, "captain")

    def test_visual_question_polishes_machine_labels_before_speaking(self) -> None:
        context = sanitize_vision_context(
            {
                "enabled": True,
                "status": "running",
                "semanticCaption": (
                    "人物：青年男性；外观和表情：戴眼镜，神情专注；"
                    "动作：静坐；环境：室内昏暗；物体：耳机、麦克风"
                ),
                "personActivity": "画面中有人",
                "personCount": 1,
                "objectsDetected": ["person"],
            }
        )

        plan = build_direct_vision_control_plan(
            "你看到了什么东西？",
            context,
            expressions=["heart", "question"],
            motions=["scene1", "captain"],
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("一位青年男性", plan.text)
        self.assertIn("戴眼镜，神情专注", plan.text)
        self.assertIn("正在静坐", plan.text)
        self.assertIn("环境是室内昏暗", plan.text)
        self.assertIn("耳机、麦克风", plan.text)
        self.assertNotIn("person", plan.text)
        self.assertNotIn("动作状态是", plan.text)
        self.assertNotIn("画面中有人", plan.text)

    def test_visual_detail_followup_uses_current_vision_without_llm(self) -> None:
        context = sanitize_vision_context(
            {
                "enabled": True,
                "status": "running",
                "semanticCaption": "人物：青年男性；外观和表情：戴眼镜，神情专注；环境：室内昏暗",
                "sceneCaption": "画面中有1人",
                "personActivity": "画面中有人",
                "personCount": 1,
                "objectsDetected": ["person"],
            }
        )

        plan = build_direct_vision_control_plan(
            "具体一点的特征呢。",
            context,
            expressions=["heart", "question"],
            motions=["scene1", "captain"],
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("青年男性", plan.text)
        self.assertIn("戴眼镜", plan.text)
        self.assertNotIn("画面中有1人", plan.text)
        self.assertNotIn("person", plan.text)

    def test_visual_question_reports_missing_context_instead_of_guessing(self) -> None:
        plan = build_direct_vision_control_plan(
            "你现在看到了什么？",
            {"enabled": False},
            expressions=["heart"],
            motions=["scene1"],
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("还没有拿到稳定的摄像头画面", plan.text)
        self.assertNotIn("风景", plan.text)


if __name__ == "__main__":
    unittest.main()
