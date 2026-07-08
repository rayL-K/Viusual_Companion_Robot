from __future__ import annotations

import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from visual_companion_robot.perception.offline_asr_service import OfflineAsrService, validate_pcm16
from visual_companion_robot.perception.sherpa_onnx_asr import SherpaOnnxASR, normalize_audio


class FakeStream:
    def __init__(self) -> None:
        self.result = type("Result", (), {"text": ""})()

    def accept_waveform(self, sample_rate: int, samples: np.ndarray) -> None:
        self.sample_rate = sample_rate
        self.samples = np.asarray(samples)


class FakeRecognizer:
    def create_stream(self) -> FakeStream:
        self.stream = FakeStream()
        return self.stream

    def decode_stream(self, stream: FakeStream) -> None:
        stream.result.text = "  你好，离线识别。  "


class FakeAsrEngine:
    def __init__(self) -> None:
        self.calls = 0
        self.load_calls = 0

    def load(self) -> None:
        self.load_calls += 1

    def model_path(self) -> Path:
        return Path("model.int8.onnx")

    def is_loaded(self) -> bool:
        return True

    def transcribe_np(self, samples: np.ndarray) -> str:
        self.calls += 1
        self.samples = samples
        return "测试文本"


class FakeVad:
    def __init__(self, ratio: float) -> None:
        self.ratio = ratio

    def speech_ratio(self, _pcm_bytes: bytes) -> float:
        return self.ratio

    def is_available(self) -> bool:
        return True

    def trim_to_speech(self, pcm_bytes: bytes) -> bytes:
        return pcm_bytes


class ConcurrentFakeAsrEngine(FakeAsrEngine):
    def __init__(self) -> None:
        super().__init__()
        self.active_calls = 0
        self.max_active_calls = 0
        self.guard = threading.Lock()

    def transcribe_np(self, samples: np.ndarray) -> str:
        with self.guard:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        time.sleep(0.02)
        with self.guard:
            self.active_calls -= 1
            self.calls += 1
        return "并发测试"


class SherpaOnnxAsrTests(unittest.TestCase):
    def test_transcribe_uses_offline_stream_and_normalizes_int16(self) -> None:
        engine = SherpaOnnxASR()
        recognizer = FakeRecognizer()
        engine._recognizer = recognizer  # type: ignore[assignment]

        text = engine.transcribe_np(np.array([0, 32767, -32768], dtype=np.int16))

        self.assertEqual(text, "你好，离线识别。")
        self.assertEqual(recognizer.stream.sample_rate, 16000)
        self.assertLessEqual(float(np.max(np.abs(recognizer.stream.samples))), 1.0)

    def test_model_discovery_prefers_int8(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_dir = Path(temp_dir) / "sense-voice"
            model_dir.mkdir()
            (model_dir / "tokens.txt").write_text("x 0", encoding="utf-8")
            (model_dir / "model.onnx").write_bytes(b"float")
            (model_dir / "model.int8.onnx").write_bytes(b"int8")
            engine = SherpaOnnxASR(model_root=temp_dir)

            self.assertEqual(engine.model_path(), model_dir / "model.int8.onnx")

    def test_normalize_audio_rejects_non_finite_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "非有限"):
            normalize_audio(np.array([0.0, np.nan], dtype=np.float32))


class OfflineAsrServiceTests(unittest.TestCase):
    @staticmethod
    def pcm(duration_ms: int = 600) -> bytes:
        sample_count = round(16000 * duration_ms / 1000)
        return np.zeros(sample_count, dtype="<i2").tobytes()

    def test_silence_does_not_load_or_call_asr(self) -> None:
        engine = FakeAsrEngine()
        service = OfflineAsrService(engine=engine, vad=FakeVad(0.0))  # type: ignore[arg-type]

        result = service.transcribe_pcm16(self.pcm())

        self.assertFalse(result.speech_detected)
        self.assertEqual(result.text, "")
        self.assertEqual(engine.calls, 0)

    def test_prepare_loads_model_before_first_utterance(self) -> None:
        engine = FakeAsrEngine()
        service = OfflineAsrService(engine=engine, vad=FakeVad(0.0))  # type: ignore[arg-type]

        service.prepare()

        self.assertEqual(engine.load_calls, 1)

    def test_speech_is_transcribed_with_metadata(self) -> None:
        engine = FakeAsrEngine()
        service = OfflineAsrService(engine=engine, vad=FakeVad(0.5))  # type: ignore[arg-type]

        result = service.transcribe_pcm16(self.pcm(900))

        self.assertTrue(result.speech_detected)
        self.assertEqual(result.text, "测试文本")
        self.assertEqual(result.duration_ms, 900)
        self.assertEqual(result.speech_ratio, 0.5)
        self.assertEqual(engine.calls, 1)

    def test_health_reports_model_and_runtime_state(self) -> None:
        service = OfflineAsrService(engine=FakeAsrEngine(), vad=FakeVad(0.0))  # type: ignore[arg-type]

        health = service.health()

        self.assertTrue(health["ok"])
        self.assertTrue(health["model_ready"])
        self.assertTrue(health["loaded"])
        self.assertTrue(health["vad_ready"])

    def test_decode_is_serialized_across_server_threads(self) -> None:
        engine = ConcurrentFakeAsrEngine()
        service = OfflineAsrService(engine=engine, vad=FakeVad(0.5))  # type: ignore[arg-type]
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(service.transcribe_pcm16, [self.pcm()] * 4))

        self.assertEqual([result.text for result in results], ["并发测试"] * 4)
        self.assertEqual(engine.calls, 4)
        self.assertEqual(engine.max_active_calls, 1)

    def test_pcm_duration_limits_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "非空"):
            validate_pcm16(b"")
        with self.assertRaisesRegex(ValueError, "16 位"):
            validate_pcm16(b"\x00")
        with self.assertRaisesRegex(ValueError, "至少"):
            validate_pcm16(self.pcm(100))
        with self.assertRaisesRegex(ValueError, "不能超过"):
            validate_pcm16(self.pcm(30_100))


if __name__ == "__main__":
    unittest.main()
