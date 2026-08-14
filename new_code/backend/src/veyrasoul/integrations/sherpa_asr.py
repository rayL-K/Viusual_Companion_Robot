"""Bounded-queue sherpa-onnx streaming Zipformer adapter."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from veyrasoul.orchestration.ports import (
    AudioAdapterCapabilities,
    AsrAdmissionHandler,
    AsrUpdate,
    AsrUpdateHandler,
)


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
    capabilities = AudioAdapterCapabilities(asr_streaming=True)

    def __init__(self, config: SherpaAsrConfig) -> None:
        self.config = config
        self._recognizer = None
        self._load_lock = threading.Lock()
        self._decode_lock = threading.Lock()
        self._async_decode_lock = asyncio.Lock()

    def create_session(
        self,
        *,
        admit: AsrAdmissionHandler | None = None,
    ) -> "SherpaAsrSession":
        # Local inference has no billable upstream request; admission is a
        # gateway-wide factory contract and is intentionally not consumed.
        del admit
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

    async def decode(self, stream, pcm16: bytes) -> tuple[str, bool]:
        """Serialize native decoding without occupying waiting executor workers.

        sherpa-onnx exposes mutable recognizer state shared by all sessions.  The
        async gate is deliberately acquired *before* entering ``to_thread`` so a
        burst of browser sessions cannot fill asyncio's shared executor with
        workers blocked on ``_decode_lock``.  Native inference itself cannot be
        cancelled safely; cancellation therefore keeps the gate until the worker
        has actually left the recognizer.
        """

        async with self._async_decode_lock:
            worker = asyncio.create_task(
                asyncio.to_thread(self._decode, stream, pcm16),
                name="sherpa-asr-native",
            )
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                while not worker.done():
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.shield(worker)
                raise

    def _reset(self, stream) -> None:
        with self._decode_lock:
            self._recognizer.reset(stream)

    async def reset(self, stream) -> None:
        """Reset native stream state under the same locks used for decode."""

        async with self._async_decode_lock:
            await asyncio.to_thread(self._reset, stream)

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
        self.queue: asyncio.Queue[tuple[int, bytes] | None] = asyncio.Queue(
            maxsize=max(10, queue_frames)
        )
        self.task: asyncio.Task[None] | None = None
        self.handler: AsrUpdateHandler | None = None
        self.last_partial = ""
        self._epoch = 0
        self._reset_required = False
        self._emit_task: asyncio.Task[None] | None = None

    @property
    def epoch(self) -> int:
        return self._epoch

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
            self.queue.put_nowait((self._epoch, bytes(pcm16)))
        except asyncio.QueueFull as exc:
            raise RuntimeError("ASR input queue exceeded one second") from exc

    async def invalidate(self) -> None:
        """Drop queued audio immediately and stale-gate any native decode in flight."""

        self._epoch += 1
        self.last_partial = ""
        self._reset_required = True
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        emit_task = self._emit_task
        if emit_task is not None and not emit_task.done():
            emit_task.cancel()

    async def close(self) -> None:
        task = self.task
        if task is None:
            return
        self.task = None
        await self.invalidate()
        if not task.done():
            await self.queue.put(None)
            await task

    async def _run(self) -> None:
        deferred: tuple[int, bytes] | None = None
        while True:
            first = deferred if deferred is not None else await self.queue.get()
            deferred = None
            if first is None:
                return
            epoch, first_pcm = first
            if self._reset_required:
                await self._reset_stale_stream()
            if epoch != self._epoch:
                continue
            frames = [first_pcm]
            stop_after_batch = False
            for _ in range(9):
                try:
                    value = self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if value is None:
                    stop_after_batch = True
                    break
                value_epoch, value_pcm = value
                if value_epoch != epoch:
                    deferred = value
                    break
                frames.append(value_pcm)
            text, endpoint = await self.owner.decode(self.stream, b"".join(frames))
            if epoch != self._epoch:
                await self._reset_stale_stream()
                if stop_after_batch:
                    return
                continue
            if text and text != self.last_partial:
                self.last_partial = text
                await self._emit(
                    AsrUpdate(text=text, final=False, epoch=epoch),
                    epoch,
                )
            if endpoint:
                if text:
                    await self._emit(
                        AsrUpdate(text=text, final=True, epoch=epoch),
                        epoch,
                    )
                self.last_partial = ""
            if stop_after_batch:
                return

    async def _reset_stale_stream(self) -> None:
        while self._reset_required:
            reset_epoch = self._epoch
            await self.owner.reset(self.stream)
            if reset_epoch == self._epoch:
                self._reset_required = False

    async def _emit(self, update: AsrUpdate, epoch: int) -> None:
        handler = self.handler
        if handler is None or epoch != self._epoch:
            return
        task = asyncio.create_task(handler(update), name="sherpa-asr-emit")
        self._emit_task = task
        try:
            await task
        except asyncio.CancelledError:
            if epoch != self._epoch:
                return
            raise
        finally:
            if self._emit_task is task:
                self._emit_task = None


def _preferred_model(root: Path, prefix: str) -> Path:
    candidates = sorted(root.glob(f"{prefix}*.onnx"), key=lambda path: ("int8" not in path.name, path.name))
    if not candidates:
        raise FileNotFoundError(f"missing {prefix} ONNX model under {root}")
    return candidates[0]


def _required(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"required ASR asset is missing: {path}")
    return path
