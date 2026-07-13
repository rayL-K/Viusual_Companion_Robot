"""ASGI gateway for cancellable V2 realtime sessions."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from veyrasoul.affect import AffectState
from veyrasoul.avatar import AvatarIntent, AvatarPhase
from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.identity import (
    AnimaId,
    InvalidIdentity,
    SessionIdentity,
    UserId,
    validate_session_hint,
)
from veyrasoul.orchestration.ports import AsrUpdate, StreamingAsrSession
from veyrasoul.personalization import ProfileConflictError, ProfileValidationError
from veyrasoul.perception import VisualSemanticScheduler
from veyrasoul.transport import BinaryKind, build_binary_frame, parse_binary_frame

from .runtime import AppServices, RuntimeSession, SessionRegistry


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CancelledTurn:
    generation: int
    turn_id: str


@dataclass(frozen=True, slots=True)
class ListeningTurn:
    generation: int
    turn_id: str


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
        self.current_turn_id = ""
        self.pending_listening: ListeningTurn | None = None
        self._lock = asyncio.Lock()

    async def start(self, user_text: str, turn_id: str | None = None) -> None:
        async with self._lock:
            current_turn_id = turn_id or uuid.uuid4().hex
            await self._start_locked(user_text, current_turn_id)

    async def listen(self) -> ListeningTurn:
        async with self._lock:
            return await self._listen_locked()

    async def start_from_asr(self, user_text: str) -> None:
        async with self._lock:
            listening = await self._listen_locked()
            await self._start_locked(user_text, listening.turn_id)

    async def cancel(self) -> CancelledTurn:
        async with self._lock:
            await _cancel_task(self.current)
            self.current = None
            generation = await self.runtime.kernel.cancel_current_turn()
            cancelled = CancelledTurn(generation, self.current_turn_id)
            self.current_turn_id = ""
            self.pending_listening = None
            return cancelled

    async def _listen_locked(self) -> ListeningTurn:
        if self.pending_listening is not None:
            return self.pending_listening
        await _cancel_task(self.current)
        self.current = None
        generation = await self.runtime.kernel.cancel_current_turn()
        turn_id = uuid.uuid4().hex
        listening = ListeningTurn(generation, turn_id)
        self.current_turn_id = turn_id
        self.pending_listening = listening
        await _emit_avatar_intent(
            self.runtime,
            self.writer,
            turn_id,
            generation,
            "listening",
        )
        return listening

    async def _start_locked(self, user_text: str, turn_id: str) -> None:
        await _cancel_task(self.current)
        await self.runtime.kernel.cancel_current_turn()
        self.current_turn_id = turn_id
        self.pending_listening = None
        self.current = asyncio.create_task(
            _run_turn(self.runtime, self.writer, turn_id, user_text),
            name=f"reply:{self.writer.session_id}:{turn_id}",
        )


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
        raw_session = websocket.query_params.get("session")
        try:
            session_id = (
                validate_session_hint(raw_session) if raw_session is not None else uuid.uuid4().hex
            )
        except InvalidIdentity as exc:
            writer = ConnectionWriter(websocket, uuid.uuid4().hex)
            await writer.event(
                "error",
                payload={"code": "invalid_session", "message": str(exc)},
            )
            await websocket.close(code=1008, reason="invalid session")
            return
        writer = ConnectionWriter(websocket, session_id)
        try:
            resolver = services.identity_resolver or _parse_session_identity
            identity = resolver(
                websocket.query_params.get("user"),
                websocket.query_params.get("anima"),
                session_id,
            )
        except InvalidIdentity as exc:
            await writer.event(
                "error",
                payload={"code": "invalid_identity", "message": str(exc)},
            )
            await websocket.close(code=1008, reason="invalid identity")
            return
        runtime = await registry.get(session_id, identity)
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
                lambda error: _handle_perception_error(error, writer),
            )
        await writer.event(
            "session.ready",
            payload={
                "protocol": 2,
                "userId": identity.user_id.value,
                "animaId": identity.anima_id.value,
                "anonymous": identity.anonymous,
                "identityAssurance": identity.assurance,
            },
        )
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
                if event_type == "settings.get":
                    await _emit_settings(runtime, writer)
                    continue
                if event_type == "settings.update":
                    try:
                        profile = runtime.profiles.update(payload)
                    except ProfileConflictError:
                        await writer.event(
                            "error",
                            payload={
                                "code": "settings_conflict",
                                "message": "角色设置已在另一处更新，请重新载入后再保存",
                            },
                        )
                        continue
                    except ProfileValidationError as exc:
                        await writer.event(
                            "error",
                            payload={"code": "invalid_settings", "message": str(exc)},
                        )
                        continue
                    except RuntimeError as exc:
                        _LOGGER.warning(
                            "Anima settings persistence failed (%s)",
                            type(exc).__name__,
                        )
                        await writer.event(
                            "error",
                            payload={
                                "code": "settings_persistence_failed",
                                "message": "角色设置暂时无法保存",
                            },
                        )
                        continue
                    await writer.event(
                        "settings.current",
                        payload={**profile.to_wire(), "updated": True},
                    )
                    continue
                if event_type == "turn.cancel":
                    cancelled = await turns.cancel()
                    await writer.event(
                        "turn.cancelled",
                        turn_id=cancelled.turn_id,
                        generation=cancelled.generation,
                    )
                    if cancelled.turn_id:
                        await _emit_avatar_intent(
                            runtime,
                            writer,
                            cancelled.turn_id,
                            cancelled.generation,
                            "idle",
                        )
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
        profile = runtime.profiles.get()
        generation, context = await runtime.kernel.begin_turn(user_text)
        await writer.event(
            "reply.phase",
            turn_id=turn_id,
            generation=generation,
            payload={"phase": "thinking", "retrievalTimedOut": context.retrieval_timed_out},
        )
        await _emit_avatar_intent(
            runtime,
            writer,
            turn_id,
            generation,
            "thinking",
            affect=context.affect,
        )
        texts: list[str] = []
        async for segment in runtime.turn_service.generate(user_text, context, profile):
            if generation != runtime.kernel.generation:
                return
            await _emit_avatar_intent(
                runtime,
                writer,
                turn_id,
                generation,
                "speaking",
                segment_index=segment.index,
            )
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
            await _emit_avatar_intent(
                runtime,
                writer,
                turn_id,
                generation,
                "idle",
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _LOGGER.warning("Reply generation failed (%s)", type(exc).__name__)
        if generation == runtime.kernel.generation:
            await writer.event(
                "error",
                turn_id=turn_id,
                generation=generation,
                payload={"code": "reply_failed", "message": "本轮回复生成失败"},
            )
            await _emit_avatar_intent(
                runtime,
                writer,
                turn_id,
                generation,
                "idle",
            )


async def _emit_avatar_intent(
    runtime: RuntimeSession,
    writer: ConnectionWriter,
    turn_id: str,
    generation: int,
    phase: AvatarPhase,
    *,
    segment_index: int | None = None,
    affect: AffectState | None = None,
) -> bool:
    if generation != runtime.kernel.generation:
        return False
    state = affect or await runtime.kernel.current_affect(generation)
    if state is None or generation != runtime.kernel.generation:
        return False
    intent = runtime.avatar_director.intent_for(state, phase=phase)
    payload = _avatar_payload(intent, state, segment_index)
    await writer.event(
        "avatar.intent",
        turn_id=turn_id,
        generation=generation,
        payload=payload,
    )
    return True


def _avatar_payload(
    intent: AvatarIntent,
    affect: AffectState,
    segment_index: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "phase": intent.phase,
        "expression": intent.expression,
        "motion": intent.motion,
        "gazeStrength": round(intent.gaze_strength, 4),
        "bodyTension": round(intent.body_tension, 4),
        "smile": round(intent.smile, 4),
        "eyeOpen": round(intent.eye_open, 4),
        "speechRate": round(intent.speech_rate, 4),
        "speechPitch": round(intent.speech_pitch, 4),
        "affect": {
            "valence": round(affect.valence, 4),
            "arousal": round(affect.arousal, 4),
            "dominance": round(affect.dominance, 4),
            "affinity": round(affect.affinity, 4),
            "trust": round(affect.trust, 4),
        },
    }
    if segment_index is not None:
        payload["segmentIndex"] = segment_index
    return payload


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
        await turns.start_from_asr(update.text)
    elif update.text:
        await turns.listen()


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


async def _handle_perception_error(
    error: Exception,
    writer: ConnectionWriter,
) -> None:
    _LOGGER.warning("Visual semantic analysis failed (%s)", type(error).__name__)
    await writer.event(
        "perception.error",
        payload={
            "code": "perception_failed",
            "message": "视觉语义分析暂时不可用",
        },
    )


async def _emit_settings(
    runtime: RuntimeSession,
    writer: ConnectionWriter,
) -> None:
    try:
        profile = runtime.profiles.get()
    except RuntimeError as exc:
        _LOGGER.warning("Anima settings read failed (%s)", type(exc).__name__)
        await writer.event(
            "error",
            payload={"code": "settings_read_failed", "message": "角色设置暂时无法读取"},
        )
        return
    await writer.event("settings.current", payload=profile.to_wire())


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


def _parse_session_identity(
    raw_user_id: object,
    raw_anima_id: object,
    session_id: str,
) -> SessionIdentity:
    if raw_user_id is not None:
        raise InvalidIdentity("显式 user 参数需要服务端认证 IdentityResolver")
    user_id = UserId.anonymous_for(session_id)
    anima_id = AnimaId.default() if raw_anima_id is None else AnimaId.parse(raw_anima_id)
    return SessionIdentity(
        user_id=user_id,
        anima_id=anima_id,
        anonymous=True,
        assurance="anonymous_session_hint",
    )
