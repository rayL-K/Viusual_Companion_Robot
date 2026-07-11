"""Bounded-queue sherpa-onnx streaming Zipformer adapter."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from veyrasoul.orchestration.ports import AsrUpdate, AsrUpdateHandler


@dataclass(frozen=True, slots=True)
class SherpaAsrConfig:
    model_dir: Path
    num_threads: int = 4
    decoding_method: str = "greedy_search"
    rule1_min_trailing_silence: float = 1.6
    rule2_min_trailing_silence: float = 0.55
    rule3_min_utterance_length: float = 20.0
    queue_frames: int = 50


class SherpaStreamingAsr:
    def __init__(self, config: SherpaAsrConfig) -> None:
        self.config = config
        self._recognizer = None
        self._load_lock = threading.Lock()
        self._decode_lock = threading.Lock()

    def create_session(self) -> "SherpaAsrSession":
        recognizer = self._load()
        return SherpaAsrSession(self, recognizer.create_stream(), self.config.queue_frames)

    async def warmup(self) -> None:
        """在健康入口开放前加载共享 recognizer。"""

        await asyncio.to_thread(self._load)

    def health(self) -> dict[str, object]:
        root = self.config.model_dir
        return {
            "ok": root.is_dir() and (root / "tokens.txt").is_file(),
            "loaded": self._recognizer is not None,
            "model_dir": str(root),
        }

    def _decode(self, stream, pcm16: bytes) -> tuple[str, bool]:
        samples = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        with self._decode_lock:
            stream.accept_waveform(16_000, samples)
            while self._recognizer.is_ready(stream):
                self._recognizer.decode_stream(stream)
            result = self._recognizer.get_result_all(stream)
            endpoint = self._recognizer.is_endpoint(stream)
            text = str(result.text or "").strip()
            if endpoint:
                self._recognizer.reset(stream)
            return text, endpoint

    def _load(self):
        if self._recognizer is not None:
            return self._recognizer
        with self._load_lock:
            if self._recognizer is not None:
                return self._recognizer
            import sherpa_onnx

            root = self.config.model_dir
            tokens = _required(root / "tokens.txt")
            encoder = _preferred_model(root, "encoder")
            decoder = _preferred_model(root, "decoder")
            joiner = _preferred_model(root, "joiner")
            rule_fsts = ",".join(
                str(path)
                for name in ("itn_zh_number.fst", "rule.fst")
                if (path := root / name).is_file()
            )
            self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(tokens),
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                num_threads=max(1, self.config.num_threads),
                decoding_method=self.config.decoding_method,
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=self.config.rule1_min_trailing_silence,
                rule2_min_trailing_silence=self.config.rule2_min_trailing_silence,
                rule3_min_utterance_length=self.config.rule3_min_utterance_length,
                model_type="zipformer",
                rule_fsts=rule_fsts,
            )
            return self._recognizer


class SherpaAsrSession:
    def __init__(self, owner: SherpaStreamingAsr, stream, queue_frames: int) -> None:
        self.owner = owner
        self.stream = stream
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=max(10, queue_frames))
        self.task: asyncio.Task[None] | None = None
        self.handler: AsrUpdateHandler | None = None
        self.last_partial = ""

    async def start(self, handler: AsrUpdateHandler) -> None:
        if self.task is not None:
            raise RuntimeError("ASR session is already started")
        self.handler = handler
        self.task = asyncio.create_task(self._run(), name="sherpa-streaming-asr")

    def submit_pcm16(self, pcm16: bytes) -> None:
        if self.task is None or self.task.done():
            raise RuntimeError("ASR session is not running")
        if not pcm16 or len(pcm16) % 2:
            raise ValueError("PCM16 frame must contain complete int16 samples")
        try:
            self.queue.put_nowait(bytes(pcm16))
        except asyncio.QueueFull as exc:
            raise RuntimeError("ASR input queue exceeded one second") from exc

    async def close(self) -> None:
        task = self.task
        if task is None:
            return
        self.task = None
        if not task.done():
            await self.queue.put(None)
            await task

    async def _run(self) -> None:
        while True:
            first = await self.queue.get()
            if first is None:
                return
            frames = [first]
            stop_after_batch = False
            for _ in range(9):
                try:
                    value = self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if value is None:
                    stop_after_batch = True
                    break
                frames.append(value)
            text, endpoint = await asyncio.to_thread(self.owner._decode, self.stream, b"".join(frames))
            if text and text != self.last_partial:
                self.last_partial = text
                await self._emit(AsrUpdate(text=text, final=False))
            if endpoint:
                if text:
                    await self._emit(AsrUpdate(text=text, final=True))
                self.last_partial = ""
            if stop_after_batch:
                return

    async def _emit(self, update: AsrUpdate) -> None:
        if self.handler is not None:
            await self.handler(update)


def _preferred_model(root: Path, prefix: str) -> Path:
    candidates = sorted(root.glob(f"{prefix}*.onnx"), key=lambda path: ("int8" not in path.name, path.name))
    if not candidates:
        raise FileNotFoundError(f"missing {prefix} ONNX model under {root}")
    return candidates[0]


def _required(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"required ASR asset is missing: {path}")
    return path
