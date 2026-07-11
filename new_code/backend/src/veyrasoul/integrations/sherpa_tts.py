"""Local zh/en sherpa-onnx TTS adapter that returns in-memory WAV audio."""

from __future__ import annotations

import asyncio
import io
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True, slots=True)
class SherpaTtsConfig:
    model_dir: Path
    sid: int = 0
    speed: float = 1.0
    num_threads: int = 4
    language: str = "zh"


class SherpaTtsSynthesizer:
    def __init__(self, config: SherpaTtsConfig) -> None:
        self.config = config
        self._engine = None
        self._load_lock = threading.Lock()

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        normalized = str(text or "").strip()
        if not normalized:
            raise ValueError("TTS text must not be empty")
        return await asyncio.to_thread(self._synthesize_sync, normalized)

    async def warmup(self) -> None:
        """在服务接收会话前加载模型，避免首轮用户承担冷启动。"""

        await asyncio.to_thread(self._load)

    def health(self) -> dict[str, object]:
        root = self.config.model_dir
        return {
            "ok": root.is_dir() and (root / "tokens.txt").is_file(),
            "loaded": self._engine is not None,
            "model_dir": str(root),
            "engine": _engine_kind(root),
        }

    def _synthesize_sync(self, text: str) -> tuple[bytes, str]:
        engine = self._load()
        audio = engine.generate(
            text,
            sid=max(0, int(self.config.sid)),
            speed=max(0.5, min(2.0, float(self.config.speed))),
        )
        samples = np.asarray(audio.samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            raise RuntimeError("sherpa-onnx returned empty audio")
        return wav_bytes(samples, int(audio.sample_rate)), "audio/wav"

    def _load(self):
        if self._engine is not None:
            return self._engine
        with self._load_lock:
            if self._engine is not None:
                return self._engine
            import sherpa_onnx

            root = self.config.model_dir
            tokens = _required(root / "tokens.txt")
            lexicon = root / "lexicon.txt"
            dict_dir = root / "dict"
            data_dir = root / "espeak-ng-data"
            engine_kind = _engine_kind(root)
            if engine_kind == "matcha":
                matcha = sherpa_onnx.OfflineTtsMatchaModelConfig(
                    acoustic_model=str(_required(root / "model-steps-3.onnx")),
                    vocoder=str(_required(root / "vocos-22khz-univ.onnx")),
                    tokens=str(tokens),
                    lexicon=str(_required(lexicon)),
                    dict_dir=str(dict_dir) if dict_dir.is_dir() else "",
                )
                model = sherpa_onnx.OfflineTtsModelConfig(
                    matcha=matcha,
                    num_threads=max(1, self.config.num_threads),
                )
            elif engine_kind == "kokoro":
                model_path = _first_existing(root, "model.int8.onnx", "model.onnx")
                kokoro = sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(model_path),
                    voices=str(_required(root / "voices.bin")),
                    tokens=str(tokens),
                    lexicon=str(lexicon) if lexicon.is_file() else "",
                    data_dir=str(data_dir) if data_dir.is_dir() else "",
                    dict_dir=str(dict_dir) if dict_dir.is_dir() else "",
                    lang=self.config.language,
                )
                model = sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=kokoro,
                    num_threads=max(1, self.config.num_threads),
                )
            else:
                model_path = _first_existing(
                    root,
                    "model.int8.onnx",
                    "vits-aishell3.int8.onnx",
                    "model.onnx",
                    "vits-aishell3.onnx",
                )
                vits = sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(model_path),
                    tokens=str(tokens),
                    lexicon=str(lexicon) if lexicon.is_file() else "",
                    data_dir=str(data_dir) if data_dir.is_dir() else "",
                    dict_dir=str(dict_dir) if dict_dir.is_dir() else "",
                )
                model = sherpa_onnx.OfflineTtsModelConfig(
                    vits=vits,
                    num_threads=max(1, self.config.num_threads),
                )
            rule_fsts = ",".join(
                str(path)
                for name in ("phone.fst", "date.fst", "number.fst")
                if (path := root / name).is_file()
            )
            tts_config = sherpa_onnx.OfflineTtsConfig(
                model=model,
                rule_fsts=rule_fsts,
                max_num_sentences=1,
            )
            self._engine = sherpa_onnx.OfflineTts(tts_config)
            return self._engine


def wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


def _first_existing(root: Path, *names: str) -> Path:
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"TTS model file is missing under {root}")


def _engine_kind(root: Path) -> str:
    if (root / "model-steps-3.onnx").is_file() and (root / "vocos-22khz-univ.onnx").is_file():
        return "matcha"
    if (root / "voices.bin").is_file():
        return "kokoro"
    return "vits"


def _required(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"required TTS asset is missing: {path}")
    return path
