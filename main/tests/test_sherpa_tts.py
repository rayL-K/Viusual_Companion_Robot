from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.voice.sherpa_tts import SherpaOnnxTTS, SherpaOnnxTTSAdapter


class FakeSherpaEngine:
    def load(self) -> None:
        self.loaded = True

    def synthesize(self, text: str, sid: int, speed: float) -> tuple[np.ndarray, int]:
        self.call = (text, sid, speed)
        return np.array([-1.2, -0.5, 0.0, 0.5, 1.2], dtype=np.float32), 16000


class SherpaOnnxTtsTests(unittest.TestCase):
    def test_adapter_writes_valid_pcm_wav_and_uses_unique_paths(self) -> None:
        engine = FakeSherpaEngine()
        adapter = SherpaOnnxTTSAdapter(engine)  # type: ignore[arg-type]

        first = adapter.generate_audio("你好", sid=2, speed=1.1)
        second = adapter.generate_audio("再见")
        self.addCleanup(adapter.cleanup, first)
        self.addCleanup(adapter.cleanup, second)

        self.assertNotEqual(first, second)
        self.assertEqual(engine.call, ("再见", 0, 1.0))
        with wave.open(first, "rb") as audio:
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getsampwidth(), 2)
            self.assertEqual(audio.getframerate(), 16000)
            self.assertEqual(audio.getnframes(), 5)

    def test_existing_model_directory_is_discovered_without_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_root = Path(temp_dir) / "vits-zh-aishell3"
            model_root.mkdir()
            for name in ("vits-aishell3.int8.onnx", "tokens.txt", "lexicon.txt"):
                (model_root / name).write_bytes(b"test")

            engine = SherpaOnnxTTS(model_dir=temp_dir, model_id="vits-zh")

            self.assertEqual(engine._ensure_model(), model_root)
            self.assertEqual(engine._find_model_file(model_root), model_root / "vits-aishell3.int8.onnx")

    def test_model_archive_rejects_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = SherpaOnnxTTS(model_dir=temp_dir, model_id="vits-zh")
            archive_buffer = io.BytesIO()
            with tarfile.open(fileobj=archive_buffer, mode="w") as bundle:
                link = tarfile.TarInfo("model.onnx")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../outside.onnx"
                bundle.addfile(link)
            archive_buffer.seek(0)

            with tarfile.open(fileobj=archive_buffer, mode="r") as bundle:
                with self.assertRaisesRegex(RuntimeError, "不安全的特殊文件"):
                    engine._extract_safely(bundle)

    def test_matcha_model_requires_acoustic_model_and_vocoder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_root = Path(temp_dir) / "matcha-icefall-zh-baker"
            model_root.mkdir()
            for name in ("model-steps-3.onnx", "vocos-22khz-univ.onnx", "tokens.txt", "lexicon.txt"):
                (model_root / name).write_bytes(b"test")

            engine = SherpaOnnxTTS(model_dir=temp_dir, model_id="matcha-zh")

            self.assertEqual(engine.model_root(), model_root)


if __name__ == "__main__":
    unittest.main()
