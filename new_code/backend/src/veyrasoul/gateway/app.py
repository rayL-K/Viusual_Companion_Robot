"""ASGI gateway for cancellable V2 realtime sessions."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.memory import HybridRetriever, MemoryStore
from veyrasoul.orchestration.context import ContextAssembler
from veyrasoul.orchestration.ports import (
    AsrUpdate,
    SpeechSynthesizer,
    StreamingAsrFactory,
    StreamingAsrSession,
    StreamingLlm,
)
from veyrasoul.orchestration.session import SessionKernel
from veyrasoul.orchestration.turn_service import TurnService
from veyrasoul.perception import VisualSemanticScheduler, VisionAnalyzer
from veyrasoul.runtime.latest_value import LatestValue
from veyrasoul.transport import BinaryKind, build_binary_frame, parse_binary_frame


@dataclass(frozen=True, slots=True)
class AppServices:
    memory_path: Path
    llm: StreamingLlm
    tts: SpeechSynthesizer
    stable_system_prompt: str
    asr: StreamingAsrFactory | None = None
    vision: VisionAnalyzer | None = None
    vision_refresh_seconds: float = 5.0
    max_sessions: int = 8
    startup: tuple[Callable[[], Awaitable[None]], ...] = ()
    shutdown: tuple[Callable[[], Awaitable[None]], ...] = ()
    web_dist: Path | None = None


@dataclass(slots=True)
class RuntimeSession:
    kernel: SessionKernel
    turn_service: TurnService


class SessionRegistry:
    def __init__(self, services: AppServices) -> None:
        self.services = services
        self.memory = MemoryStore(services.memory_path)
        self._sessions: OrderedDict[str, RuntimeSession] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> RuntimeSession:
        async with self._lock:
            existing = self._sessions.get(session_id)
            if existing:
                self._sessions.move_to_end(session_id)
                return existing
            visual = LatestValue()
            retriever = HybridRetriever(self.memory)
            context = ContextAssembler(visual, retriever)
            runtime = RuntimeSession(
                kernel=SessionKernel(session_id, self.memory, context),
                turn_service=TurnService(
                    self.services.llm,
                    self.services.tts,
                    self.services.stable_system_prompt,
                ),
            )
            self._sessions[session_id] = runtime
            while len(self._sessions) > max(1, self.services.max_sessions):
                self._sessions.popitem(last=False)
            return runtime


class ConnectionWriter:
    def __init__(self, websocket: WebSocket, session_id: str) -> None:
        self.websocket = websocket
        self.session_id = session_id
        self._sequence = 0
        self._lock = asyncio.Lock()

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    async def event(
        self,
        event_type: str,
        *,
        turn_id: str = "",
        generation: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            await self.websocket.send_json(
                {
                    "v": 2,
                    "type": event_type,
                    "sessionId": self.session_id,
                    "turnId": turn_id,
                    "generation": generation,
                    "seq": self._next_sequence(),
                    "sentAtMs": int(time.time() * 1000),
                    "payload": payload or {},
                }
            )

    async def reply_segment(
        self,
        *,
        turn_id: str,
        generation: int,
        index: int,
        text: str,
        audio: bytes,
        content_type: str,
    ) -> None:
        """Send audio first, then expose its text; WebSocket ordering keeps them synchronized."""

        async with self._lock:
            audio_sequence = self._next_sequence()
            await self.websocket.send_bytes(
                build_binary_frame(
                    BinaryKind.AUDIO,
                    audio_sequence,
                    int(time.time() * 1000),
                    audio,
                )
            )
            await self.websocket.send_json(
                {
                    "v": 2,
                    "type": "reply.segment.ready",
                    "sessionId": self.session_id,
                    "turnId": turn_id,
                    "generation": generation,
                    "seq": self._next_sequence(),
                    "sentAtMs": int(time.time() * 1000),
                    "payload": {
                        "index": index,
                        "text": text,
                        "audioSeq": audio_sequence,
                        "contentType": content_type,
                    },
                }
            )


class TurnController:
    def __init__(self, runtime: RuntimeSession, writer: ConnectionWriter) -> None:
        self.runtime = runtime
        self.writer = writer
        self.current: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self, user_text: str, turn_id: str | None = None) -> None:
        async with self._lock:
            await _cancel_task(self.current)
            await self.runtime.kernel.cancel_current_turn()
            current_turn_id = turn_id or uuid.uuid4().hex
            self.current = asyncio.create_task(
                _run_turn(self.runtime, self.writer, current_turn_id, user_text),
                name=f"reply:{self.writer.session_id}:{current_turn_id}",
            )

    async def cancel(self) -> int:
        async with self._lock:
            await _cancel_task(self.current)
            self.current = None
            return await self.runtime.kernel.cancel_current_turn()


def create_app(services: AppServices) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        for start in services.startup:
            await start()
        try:
            yield
        finally:
            for close in reversed(services.shutdown):
                await close()

    app = FastAPI(title="VeyraSoul Realtime Gateway", version="2.0", lifespan=lifespan)
    registry = SessionRegistry(services)
    app.state.registry = registry

    @app.get("/v2/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "protocol": 2,
            "service": "veyrasoul-gateway",
            "streaming_asr": services.asr is not None,
        }

    @app.websocket("/v2/realtime")
    async def realtime(websocket: WebSocket) -> None:
        await websocket.accept()
        session_id = _clean_identifier(websocket.query_params.get("session")) or uuid.uuid4().hex
        runtime = await registry.get(session_id)
        writer = ConnectionWriter(websocket, session_id)
        turns = TurnController(runtime, writer)
        asr_session = services.asr.create_session() if services.asr else None
        vision_scheduler = (
            VisualSemanticScheduler(
                services.vision,
                refresh_seconds=services.vision_refresh_seconds,
            )
            if services.vision
            else None
        )
        if asr_session:
            await asr_session.start(lambda update: _handle_asr_update(update, writer, turns))
        if vision_scheduler:
            await vision_scheduler.start(
                lambda snapshot: _handle_visual_snapshot(snapshot, runtime, writer),
                lambda error: writer.event(
                    "perception.error",
                    payload={"message": str(error)[:240]},
                ),
            )
        await writer.event("session.ready", payload={"protocol": 2})
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if raw_bytes := message.get("bytes"):
                    await _handle_binary(raw_bytes, writer, asr_session, vision_scheduler)
                    continue
                raw_text = message.get("text")
                if raw_text is None:
                    continue
                try:
                    event = _parse_client_event(raw_text)
                except ValueError as exc:
                    await writer.event("error", payload={"code": "invalid_event", "message": str(exc)})
                    continue
                event_type = event["type"]
                payload = event["payload"]
                if event_type == "session.hello":
                    await writer.event("session.hello.ack", payload={"protocol": 2})
                    continue
                if event_type == "turn.cancel":
                    generation = await turns.cancel()
                    await writer.event("turn.cancelled", generation=generation)
                    continue
                if event_type == "turn.user_text":
                    text = str(payload.get("text") or "").strip()
                    if not text:
                        await writer.event(
                            "error",
                            payload={"code": "empty_user_text", "message": "用户输入不能为空"},
                        )
                        continue
                    turn_id = _clean_identifier(payload.get("turnId")) or uuid.uuid4().hex
                    await turns.start(text, turn_id)
                    continue
                await writer.event(
                    "error",
                    payload={"code": "unsupported_event", "message": f"不支持事件 {event_type}"},
                )
        except WebSocketDisconnect:
            pass
        finally:
            if vision_scheduler:
                await vision_scheduler.close()
            if asr_session:
                await asr_session.close()
            await turns.cancel()

    if services.web_dist is not None:
        web_dist = services.web_dist.resolve()
        if not (web_dist / "index.html").is_file():
            raise ValueError(f"web_dist 缺少 index.html：{web_dist}")
        # 放在 API/WS 路由之后；生产入口因此能以同一端口提供 HTTPS 回源与实时协议。
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app


async def _run_turn(
    runtime: RuntimeSession,
    writer: ConnectionWriter,
    turn_id: str,
    user_text: str,
) -> None:
    generation = 0
    try:
        generation, context = await runtime.kernel.begin_turn(user_text)
        await writer.event(
            "reply.phase",
            turn_id=turn_id,
            generation=generation,
            payload={"phase": "thinking", "retrievalTimedOut": context.retrieval_timed_out},
        )
        texts: list[str] = []
        async for segment in runtime.turn_service.generate(user_text, context):
            if generation != runtime.kernel.generation:
                return
            await writer.reply_segment(
                turn_id=turn_id,
                generation=generation,
                index=segment.index,
                text=segment.text,
                audio=segment.audio,
                content_type=segment.content_type,
            )
            texts.append(segment.text)
        reply = "".join(texts).strip()
        if not reply:
            raise RuntimeError("模型没有生成可播放回复")
        committed = await runtime.kernel.complete_turn(
            generation,
            turn_id,
            user_text,
            reply,
        )
        if committed:
            await writer.event(
                "reply.completed",
                turn_id=turn_id,
                generation=generation,
                payload={"text": reply, "segments": len(texts)},
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        if generation == runtime.kernel.generation:
            await writer.event(
                "error",
                turn_id=turn_id,
                generation=generation,
                payload={"code": "reply_failed", "message": "本轮回复生成失败"},
            )


async def _handle_binary(
    raw: bytes,
    writer: ConnectionWriter,
    asr_session: StreamingAsrSession | None,
    vision_scheduler: VisualSemanticScheduler | None,
) -> None:
    try:
        frame = parse_binary_frame(raw)
    except ValueError as exc:
        await writer.event("error", payload={"code": "invalid_binary", "message": str(exc)})
        return
    if frame.kind is BinaryKind.PCM16 and asr_session is not None:
        try:
            asr_session.submit_pcm16(frame.payload)
        except (ValueError, RuntimeError) as exc:
            await writer.event("error", payload={"code": "asr_backpressure", "message": str(exc)})
    if frame.kind is BinaryKind.JPEG and vision_scheduler is not None:
        try:
            vision_scheduler.submit_jpeg(frame.payload, frame.sequence, frame.timestamp_ms)
        except (ValueError, RuntimeError) as exc:
            await writer.event(
                "error",
                payload={"code": "invalid_visual_frame", "message": str(exc)},
            )
    if frame.flags & 0x01:
        await writer.event(
            "media.accepted",
            payload={"kind": frame.kind.name.lower(), "sequence": frame.sequence, "bytes": len(frame.payload)},
        )


async def _handle_asr_update(
    update: AsrUpdate,
    writer: ConnectionWriter,
    turns: TurnController,
) -> None:
    event_type = "asr.final" if update.final else "asr.partial"
    await writer.event(event_type, payload={"text": update.text})
    if update.final and update.text:
        await turns.start(update.text)


async def _handle_visual_snapshot(
    snapshot: VisualSnapshot,
    runtime: RuntimeSession,
    writer: ConnectionWriter,
) -> None:
    await runtime.kernel.visual.publish(snapshot)
    await writer.event(
        "perception.snapshot",
        payload={
            "summary": snapshot.prompt_summary(),
            "sequence": snapshot.sequence,
            "observedAtMs": snapshot.observed_at_ms,
            "confidence": snapshot.confidence,
        },
    )


async def _cancel_task(task: asyncio.Task[None] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _parse_client_event(raw: str) -> dict[str, Any]:
    import json

    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("事件必须是有效 JSON") from exc
    if not isinstance(event, dict) or event.get("v") != 2 or not isinstance(event.get("type"), str):
        raise ValueError("事件协议版本或类型无效")
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValueError("事件 payload 必须是对象")
    return {"type": event["type"], "payload": payload}


def _clean_identifier(value: object) -> str:
    text = str(value or "").strip()
    return "".join(character for character in text if character.isalnum() or character in "-_:")[:100]
