from __future__ import annotations

import base64
import json
import sys
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.perception.emotion import FerPlusEmotionRecognizer
from visual_companion_robot.perception import emotion_server
from visual_companion_robot.perception.active_speaker import ActiveSpeakerBusyError
from visual_companion_robot.perception.emotion_server import EmotionRequestHandler


class FakeEmotionEngine:
    def input_names(self) -> list[str]:
        return ["Input3"]

    def run(self, output_names, input_feed):  # type: ignore[no-untyped-def]
        self.input_feed = input_feed
        return [np.array([[0.1, 3.0, 0.2, 0.3, 1.0, 0.8, 0.4, 0.1]], dtype=np.float32)]


class FerPlusEmotionRecognizerTests(unittest.TestCase):
    def test_classify_uses_public_engine_contract_and_normalized_labels(self) -> None:
        recognizer = FerPlusEmotionRecognizer()
        engine = FakeEmotionEngine()
        recognizer._engine = engine  # type: ignore[assignment]

        result = recognizer.classify(np.zeros((64, 64, 3), dtype=np.uint8))

        self.assertEqual(result.emotion, "happy")
        self.assertIn("Input3", engine.input_feed)
        self.assertEqual(set(result.full_scores), {"neutral", "happy", "surprise", "sad", "angry"})
        self.assertAlmostEqual(sum(result.full_scores.values()), 1.0, places=6)
        self.assertEqual(result.confidence, result.full_scores["happy"])

    def test_classify_rejects_unexpected_output_shape(self) -> None:
        recognizer = FerPlusEmotionRecognizer()
        engine = FakeEmotionEngine()
        engine.run = lambda output_names, input_feed: [np.zeros((1, 7), dtype=np.float32)]  # type: ignore[method-assign]
        recognizer._engine = engine  # type: ignore[assignment]

        with self.assertRaisesRegex(RuntimeError, "输出维度无效"):
            recognizer.classify(np.zeros((64, 64), dtype=np.uint8))


class EmotionHttpBoundaryTests(unittest.TestCase):
    def test_active_speaker_rejects_concurrent_request_before_decoding_frames(self) -> None:
        handler = EmotionRequestHandler.__new__(EmotionRequestHandler)
        payload = {
            "sample_rate": 16_000,
            "audio_pcm_base64": base64.b64encode(b"\0\0" * 16_000).decode("ascii"),
            "frames": [{"image": "not-decoded-while-busy"}] * 4,
        }
        old_face_analyzer = emotion_server._face_analyzer
        old_active_speaker = emotion_server._active_speaker
        emotion_server._face_analyzer = object()  # type: ignore[assignment]
        emotion_server._active_speaker = object()  # type: ignore[assignment]
        emotion_server._active_speaker_request_lock.acquire()
        try:
            with self.assertRaises(ActiveSpeakerBusyError):
                handler._classify_active_speaker(payload)
        finally:
            emotion_server._active_speaker_request_lock.release()
            emotion_server._face_analyzer = old_face_analyzer
            emotion_server._active_speaker = old_active_speaker

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), EmotionRequestHandler)
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def request_json(self, body: str) -> tuple[int, dict]:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(
            "POST",
            "/emotion",
            body=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, payload

    def request_health(self, origin: str = "") -> tuple[int, dict, str | None]:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Origin": origin} if origin else {}
        connection.request("GET", "/health", headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        allowed_origin = response.getheader("Access-Control-Allow-Origin")
        connection.close()
        return response.status, payload, allowed_origin

    def test_health_and_cors_are_limited_to_local_origins(self) -> None:
        status, payload, allowed = self.request_health("https://malicious.example")
        self.assertEqual(status, 403)
        self.assertIn("Origin", payload["error"])
        self.assertIsNone(allowed)

        origin = "http://127.0.0.1:5174"
        status, payload, allowed = self.request_health(origin)
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "visual-companion-emotion")
        self.assertEqual(allowed, origin)

    def test_rejects_empty_non_object_and_oversized_requests(self) -> None:
        status, error = self.request_json("")
        self.assertEqual(status, 400)
        self.assertIn("空", error["error"])

        status, error = self.request_json("[]")
        self.assertEqual(status, 400)
        self.assertIn("JSON 对象", error["error"])

        status, error = self.request_json("{}")
        self.assertEqual(status, 400)
        self.assertIn("image", error["error"])

        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.putrequest("POST", "/emotion")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(2 * 1024 * 1024 + 1))
        connection.endheaders()
        response = connection.getresponse()
        status = response.status
        error = json.loads(response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(status, 413)
        self.assertIn("2 MiB", error["error"])


if __name__ == "__main__":
    unittest.main()
