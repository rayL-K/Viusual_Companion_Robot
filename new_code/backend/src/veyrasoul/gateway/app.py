"""ASGI gateway for cancellable Anima realtime sessions."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from veyrasoul import __version__
from veyrasoul.affect import AffectState
from veyrasoul.auth import AuthenticationError, AuthPrincipal
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
from veyrasoul.personalization import (
    CatalogError,
    ProfileConflictError,
    ProfileValidationError,
)
from veyrasoul.perception import VisualSemanticScheduler
from veyrasoul.telemetry import (
    TraceAttributes,
    TracePoint,
    TraceStage,
    TurnTrace,
    TurnTraceDimensions,
)
from veyrasoul.transport import BinaryKind, parse_binary_frame

from .admission import (
    AdmissionGate,
    ConnectionBudget,
    ConnectionLease,
    TurnLease,
    client_key,
)
from .realtime_writer import (
    ConnectionWriter,
    RealtimeClientTooSlowError,
    ReplyWriteResult,
)
from .runtime import (
    AppServices,
    RuntimeSession,
    RuntimeSessionLease,
    SessionCapacityError,
    SessionRegistry,
)


_LOGGER = logging.getLogger(__name__)
_MAX_CONTROL_EVENT_CHARS = 64 * 1024
_MAX_USER_TEXT_CHARS = 2_000
_MAX_PCM_FRAME_BYTES = 6_400
_MAX_ADMISSION_BODY_BYTES = 4_096


@dataclass(frozen=True, slots=True)
class CancelledTurn:
    generation: int
    turn_id: str


@dataclass(frozen=True, slots=True)
class ListeningTurn:
    generation: int
    turn_id: str


@dataclass(slots=True)
class RealtimeHandshake:
    session_id: str
    identity: SessionIdentity
    anima_lease: Any | None = None
    access_token: str = field(default="", repr=False)
    auth_session_id: str = ""
    auth_expires_at_ms: int = 0

    async def release(self) -> None:
        lease = self.anima_lease
        if lease is None:
            return
        self.anima_lease = None
        await asyncio.to_thread(lease.__exit__, None, None, None)

    async def maintain(self, services: AppServices) -> None:
        """Revalidate revocable auth and renew the durable data lease."""

        if self.access_token:
            authenticator = services.realtime_authenticator
            if authenticator is None:
                raise RealtimeHandshakeError(4401, "authentication unavailable")
            try:
                principal = await asyncio.to_thread(authenticator, self.access_token)
            except (AuthenticationError, ValueError):
                raise RealtimeHandshakeError(
                    4401, "authentication expired or revoked"
                ) from None
            except Exception as exc:
                _LOGGER.warning(
                    "Realtime session revalidation failed (%s)",
                    type(exc).__name__,
                )
                raise RealtimeHandshakeError(
                    1011, "authentication service unavailable"
                ) from None
            now_ms = int(time.time() * 1000)
            if (
                not isinstance(principal, AuthPrincipal)
                or principal.user_id != self.identity.user_id
                or principal.session_id != self.auth_session_id
                or principal.expires_at_ms <= now_ms
            ):
                raise RealtimeHandshakeError(
                    4401, "authentication expired or revoked"
                )
            self.auth_expires_at_ms = principal.expires_at_ms
        if self.anima_lease is not None:
            try:
                await asyncio.to_thread(self.anima_lease.renew)
            except Exception as exc:
                _LOGGER.warning(
                    "Realtime Anima lease renewal failed (%s)",
                    type(exc).__name__,
                )
                raise RealtimeHandshakeError(
                    4403, "Anima lease is no longer available"
                ) from None


class RealtimeHandshakeError(RuntimeError):
    def __init__(self, close_code: int, reason: str) -> None:
        super().__init__(reason)
        self.close_code = close_code
        self.reason = reason

class TurnController:
    def __init__(
        self,
        runtime: RuntimeSession,
        writer: ConnectionWriter,
        admission: AdmissionGate,
        connection: ConnectionLease,
    ) -> None:
        self.runtime = runtime
        self.writer = writer
        self.admission = admission
        self.connection = connection
        self.current: asyncio.Task[None] | None = None
        self.current_trace: TurnTrace | None = None
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

    async def start_from_asr(self, user_text: str, *, final_monotonic_ns: int) -> None:
        async with self._lock:
            listening = await self._listen_locked()
            await self._start_locked(
                user_text,
                listening.turn_id,
                asr_final_monotonic_ns=final_monotonic_ns,
            )

    async def cancel(self) -> CancelledTurn:
        async with self._lock:
            await self._close_current_task_locked()
            generation = await self.runtime.kernel.cancel_current_turn()
            cancelled = CancelledTurn(generation, self.current_turn_id)
            self.current_turn_id = ""
            self.pending_listening = None
            return cancelled

    async def _listen_locked(self) -> ListeningTurn:
        if self.pending_listening is not None:
            return self.pending_listening
        await self._close_current_task_locked()
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

    async def _start_locked(
        self,
        user_text: str,
        turn_id: str,
        *,
        asr_final_monotonic_ns: int | None = None,
    ) -> None:
        await self._close_current_task_locked()
        cancelled_generation = await self.runtime.kernel.cancel_current_turn()
        turn_lease, admission_failure = await self.admission.try_turn(self.connection)
        if turn_lease is None:
            self.current_turn_id = ""
            self.pending_listening = None
            await self.writer.event(
                "error",
                turn_id=turn_id,
                generation=cancelled_generation,
                payload={
                    "code": admission_failure.code if admission_failure else "server_busy",
                    "message": (
                        admission_failure.reason
                        if admission_failure
                        else "Anima 正在忙，请稍后再试"
                    ),
                },
            )
            await _emit_avatar_intent(
                self.runtime,
                self.writer,
                turn_id,
                cancelled_generation,
                "idle",
            )
            return
        self.current_turn_id = turn_id
        self.pending_listening = None
        trace = self.runtime.trace.start(
            TurnTraceDimensions(
                session_id=self.writer.session_id,
                turn_id=turn_id,
                generation=cancelled_generation + 1,
                user_id=self.runtime.identity.user_id.value,
                anima_id=self.runtime.identity.anima_id.value,
            )
        )
        if asr_final_monotonic_ns is not None:
            trace.mark_at(
                TracePoint.ASR_FINAL,
                asr_final_monotonic_ns,
                stage=TraceStage.ASR,
            )
        self.current_trace = trace
        try:
            self.current = asyncio.create_task(
                _run_turn(
                    self.runtime,
                    self.writer,
                    turn_id,
                    user_text,
                    trace,
                    turn_lease,
                ),
                name=f"reply:{self.writer.session_id}:{turn_id}",
            )
        except BaseException:
            await turn_lease.release()
            raise

    async def _close_current_task_locked(self) -> None:
        trace = self.current_trace
        await _cancel_task(self.current)
        if trace is not None:
            trace.cancel()
        self.current = None
        self.current_trace = None
        self.writer.reset_audio_timeline()


@dataclass(slots=True)
class RealtimeConnectionResources:
    """Own and deterministically close every resource allocated by one socket."""

    connection: ConnectionLease
    handshake: RealtimeHandshake
    runtime_lease: RuntimeSessionLease | None = None
    turns: TurnController | None = None
    asr_session: StreamingAsrSession | None = None
    vision_scheduler: VisualSemanticScheduler | None = None
    _closed: bool = field(default=False, init=False, repr=False)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        cancelled: asyncio.CancelledError | None = None
        closers = (
            (
                "visual scheduler",
                self.vision_scheduler.close
                if self.vision_scheduler is not None
                else None,
            ),
            (
                "ASR session",
                self.asr_session.close if self.asr_session is not None else None,
            ),
            ("turn controller", self.turns.cancel if self.turns is not None else None),
            (
                "runtime session lease",
                self.runtime_lease.release
                if self.runtime_lease is not None
                else None,
            ),
            ("connection lease", self.connection.release),
            ("Anima lease", self.handshake.release),
        )
        for label, close in closers:
            if close is None:
                continue
            try:
                await close()
            except asyncio.CancelledError as exc:
                cancelled = cancelled or exc
            except Exception as exc:
                _LOGGER.warning(
                    "Realtime %s cleanup failed (%s)",
                    label,
                    type(exc).__name__,
                )
        if cancelled is not None:
            raise cancelled


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
            await admission.aclose()

    app = FastAPI(title="Anima Realtime Gateway", version=__version__, lifespan=lifespan)
    registry = SessionRegistry(services)
    admission = AdmissionGate(services.admission)
    app.state.registry = registry
    app.state.admission_gate = admission

    @app.get("/v2/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "protocol": 2,
            "service": "anima-gateway",
            "version": __version__,
            "releaseDigest": services.release_digest,
            "streaming_asr": (
                any(
                    item.capability.value == "asr"
                    for item in services.provider_resolver.available_providers()
                )
                if services.provider_resolver is not None
                else services.asr is not None
            ),
            "tocEnabled": (
                services.toc_router is not None
                and services.realtime_authenticator is not None
            ),
            "anonymousRealtimeEnabled": services.allow_anonymous_realtime,
        }

    @app.get("/v2/admission/status")
    async def admission_status(request: Request) -> JSONResponse:
        ready = (
            not services.admission.required
            or (
                admission.verify_token(request.cookies.get(AdmissionGate.COOKIE_NAME))
                and admission.verify_device_token(
                    request.cookies.get(AdmissionGate.DEVICE_COOKIE_NAME)
                )
            )
        )
        response = JSONResponse(
            {
                "required": services.admission.required,
                "ready": ready,
                "siteKey": services.admission.turnstile_site_key if not ready else "",
            }
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.post("/v2/admission/verify")
    async def verify_admission(request: Request) -> JSONResponse:
        if not services.admission.required:
            return JSONResponse({"ok": True})
        try:
            payload = await _read_bounded_json(request, _MAX_ADMISSION_BODY_BYTES)
        except ValueError:
            return JSONResponse({"ok": False, "code": "invalid_challenge"}, status_code=400)
        token = str(payload.get("token") or "") if isinstance(payload, dict) else ""
        if not await admission.verify_challenge(token, client_key(request)):
            return JSONResponse({"ok": False, "code": "challenge_failed"}, status_code=403)

        existing_device = request.cookies.get(AdmissionGate.DEVICE_COOKIE_NAME)
        device_token = (
            existing_device
            if admission.verify_device_token(existing_device)
            else admission.issue_device_token()
        )
        response = JSONResponse({"ok": True})
        _set_secure_cookie(
            response,
            AdmissionGate.COOKIE_NAME,
            admission.issue_token(),
            services.admission.token_ttl_seconds,
        )
        _set_secure_cookie(
            response,
            AdmissionGate.DEVICE_COOKIE_NAME,
            device_token,
            services.admission.device_ttl_seconds,
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.websocket("/v2/realtime")
    async def realtime(websocket: WebSocket) -> None:
        handshake_failure = admission.validate_handshake(websocket)
        if handshake_failure is not None:
            await websocket.close(
                code=handshake_failure.close_code,
                reason=handshake_failure.reason,
            )
            return
        try:
            handshake = await _authenticate_realtime_handshake(websocket, services, admission)
        except RealtimeHandshakeError as exc:
            await websocket.close(code=exc.close_code, reason=exc.reason)
            return
        connection, connection_failure = await admission.try_connect(client_key(websocket))
        if connection is None:
            await handshake.release()
            await websocket.close(
                code=connection_failure.close_code if connection_failure else 1013,
                reason=(
                    connection_failure.reason
                    if connection_failure
                    else "实时连接已满，请稍后重试"
                ),
            )
            return
        resources = RealtimeConnectionResources(connection, handshake)
        try:
            await websocket.accept()
        except Exception:
            await resources.close()
            raise
        session_id = handshake.session_id
        identity = handshake.identity
        writer = ConnectionWriter(
            websocket,
            session_id,
            send_timeout_seconds=services.websocket_send_timeout_seconds,
        )
        try:
            runtime_lease = await registry.acquire(session_id, identity)
            resources.runtime_lease = runtime_lease
            runtime = runtime_lease.runtime
            writer.configure_streaming_audio(runtime.turn_service.tts)
            turns = TurnController(runtime, writer, admission, connection)
            resources.turns = turns
            asr_session = (
                runtime.asr.create_session(
                    admit=lambda: admission.try_asr(connection),
                )
                if runtime.asr
                else None
            )
            resources.asr_session = asr_session
            vision_scheduler = (
                VisualSemanticScheduler(
                    runtime.vision,
                    refresh_seconds=services.vision_refresh_seconds,
                )
                if runtime.vision
                else None
            )
            resources.vision_scheduler = vision_scheduler
            if asr_session:
                await asr_session.start(
                    lambda update: _handle_asr_update(
                        update,
                        writer,
                        turns,
                        asr_session,
                    )
                )
            if vision_scheduler:
                await vision_scheduler.start(
                    lambda snapshot: _handle_visual_snapshot(snapshot, runtime, writer),
                    lambda error: _handle_perception_error(error, writer),
                )
            ready_payload: dict[str, Any] = {
                "protocol": 2,
                "userId": identity.user_id.value,
                "animaId": identity.anima_id.value,
                "anonymous": identity.anonymous,
                "identityAssurance": identity.assurance,
            }
            if writer.server_capabilities:
                ready_payload["serverCapabilities"] = list(writer.server_capabilities)
            await writer.event("session.ready", payload=ready_payload)
        except SessionCapacityError:
            with contextlib.suppress(Exception):
                await websocket.close(code=1013, reason="realtime session capacity reached")
            await resources.close()
            return
        except RealtimeClientTooSlowError:
            await resources.close()
            return
        except Exception:
            await resources.close()
            raise
        connected_at = time.monotonic()
        last_client_activity = connected_at
        next_maintenance = connected_at + min(
            services.realtime_reauth_seconds,
            services.realtime_lease_renew_seconds,
        )
        try:
            while True:
                now = time.monotonic()
                if handshake.access_token and now >= next_maintenance:
                    try:
                        await handshake.maintain(services)
                    except RealtimeHandshakeError as exc:
                        await websocket.close(
                            code=exc.close_code,
                            reason=exc.reason,
                        )
                        break
                    next_maintenance = time.monotonic() + min(
                        services.realtime_reauth_seconds,
                        services.realtime_lease_renew_seconds,
                    )
                idle_remaining = (
                    services.admission.idle_timeout_seconds
                    - (now - last_client_activity)
                )
                session_remaining = (
                    services.admission.max_session_seconds - (now - connected_at)
                )
                maintenance_remaining = (
                    max(0.0, next_maintenance - now)
                    if handshake.access_token
                    else float("inf")
                )
                receive_timeout = min(
                    idle_remaining,
                    session_remaining,
                    maintenance_remaining,
                )
                if receive_timeout <= 0:
                    await websocket.close(code=1001, reason="session expired")
                    break
                try:
                    message = await asyncio.wait_for(
                        websocket.receive(),
                        timeout=receive_timeout,
                    )
                except asyncio.TimeoutError:
                    timed_out_at = time.monotonic()
                    if (
                        handshake.access_token
                        and timed_out_at - last_client_activity
                        < services.admission.idle_timeout_seconds
                        and timed_out_at - connected_at
                        < services.admission.max_session_seconds
                    ):
                        continue
                    await websocket.close(code=1001, reason="session expired")
                    break
                last_client_activity = time.monotonic()
                if message.get("type") == "websocket.disconnect":
                    break
                if raw_bytes := message.get("bytes"):
                    if not connection.budget.accept_binary(len(raw_bytes)):
                        await writer.event(
                            "error",
                            payload={
                                "code": "media_rate_limited",
                                "message": "媒体上传过快，已丢弃当前帧",
                            },
                        )
                        continue
                    await _handle_binary(
                        raw_bytes,
                        writer,
                        asr_session,
                        vision_scheduler,
                        connection.budget,
                    )
                    continue
                raw_text = message.get("text")
                if raw_text is None:
                    continue
                if not connection.budget.accept_control():
                    await websocket.close(code=1008, reason="control rate exceeded")
                    break
                try:
                    event = _parse_client_event(raw_text)
                except InvalidIdentity:
                    await writer.event(
                        "error",
                        payload={
                            "code": "identity_forgery",
                            "message": "用户身份只能由已认证的握手确定",
                        },
                    )
                    await websocket.close(code=1008, reason="identity forgery")
                    break
                except ValueError as exc:
                    await writer.event("error", payload={"code": "invalid_event", "message": str(exc)})
                    continue
                event_type = event["type"]
                payload = event["payload"]
                if event_type == "session.hello":
                    negotiated = writer.negotiate(payload.get("capabilities"))
                    await writer.event(
                        "session.hello.ack",
                        payload={
                            "protocol": 2,
                            "capabilities": list(negotiated),
                        },
                    )
                    continue
                if event_type == "session.heartbeat":
                    await writer.event("session.heartbeat.ack")
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
                    if asr_session:
                        await asr_session.invalidate()
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
                    if len(text) > _MAX_USER_TEXT_CHARS:
                        await writer.event(
                            "error",
                            payload={
                                "code": "user_text_too_long",
                                "message": f"单次输入不能超过 {_MAX_USER_TEXT_CHARS} 个字符",
                            },
                        )
                        continue
                    turn_id = _clean_identifier(payload.get("turnId")) or uuid.uuid4().hex
                    if asr_session:
                        await asr_session.invalidate()
                    await turns.start(text, turn_id)
                    continue
                await writer.event(
                    "error",
                    payload={"code": "unsupported_event", "message": f"不支持事件 {event_type}"},
                )
        except (WebSocketDisconnect, RealtimeClientTooSlowError):
            pass
        finally:
            await resources.close()

    if services.auth_router is not None and services.toc_router is not None:
        app.include_router(services.auth_router)
        app.include_router(services.toc_router)

    if services.web_dist is not None:
        web_dist = services.web_dist.resolve()
        if not (web_dist / "index.html").is_file():
            raise ValueError(f"web_dist 缺少 index.html：{web_dist}")
        # 放在 API/WS 路由之后；生产入口因此能以同一端口提供 HTTPS 回源与实时协议。
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app


def _set_secure_cookie(
    response: JSONResponse,
    name: str,
    value: str,
    max_age: int,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )


async def _read_bounded_json(request: Request, limit: int) -> object:
    """在 JSON 解析前限制真实流量，避免 chunked body 绕过 Content-Length。"""

    content_length = request.headers.get("content-length")
    if content_length and (not content_length.isdecimal() or int(content_length) > limit):
        raise ValueError("request body exceeds limit")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise ValueError("request body exceeds limit")
        body.extend(chunk)
    if not body:
        raise ValueError("request body is empty")
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be valid JSON") from exc


async def _run_turn(
    runtime: RuntimeSession,
    writer: ConnectionWriter,
    turn_id: str,
    user_text: str,
    trace: TurnTrace,
    turn_lease: TurnLease,
) -> None:
    generation = 0
    try:
        profile = runtime.profile_for_turn()
        generation, context = await runtime.kernel.begin_turn(user_text)
        trace.bind_generation(generation)
        trace.mark(
            TracePoint.CONTEXT_READY,
            attributes=TraceAttributes(retrieval_timed_out=context.retrieval_timed_out),
        )
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
        first_frame_sent = False
        async for segment in runtime.turn_service.generate(
            user_text,
            context,
            profile,
            trace=trace,
            stream_audio=writer.streaming_audio_enabled,
        ):
            try:
                if generation != runtime.kernel.generation:
                    trace.cancel()
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
                    trace.cancel()
                    return
                write_result = await writer.reply_segment(
                    turn_id=turn_id,
                    generation=generation,
                    index=segment.index,
                    text=segment.text,
                    audio=segment.audio,
                    content_type=segment.content_type,
                    audio_stream=segment.audio_stream,
                )
                if not first_frame_sent:
                    first_frame_sent = True
                    trace.mark_at(
                        TracePoint.FIRST_REPLY_FRAME_SENT,
                        write_result.first_frame_sent_ns,
                        attributes=TraceAttributes(
                            segment_index=segment.index,
                            audio_bytes=write_result.audio_bytes,
                            content_type=segment.content_type,
                        ),
                    )
                texts.append(segment.text)
            finally:
                if segment.audio_stream is not None:
                    with contextlib.suppress(Exception):
                        await segment.audio_stream.aclose()
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
            trace.complete()
        else:
            trace.cancel()
    except asyncio.CancelledError:
        trace.cancel()
        raise
    except RealtimeClientTooSlowError as exc:
        trace.fail(exc)
        _LOGGER.warning("Realtime client stopped draining output")
    except Exception as exc:
        trace.fail(exc)
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
    finally:
        await turn_lease.release()


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
    budget: ConnectionBudget | None = None,
) -> None:
    try:
        frame = parse_binary_frame(raw)
    except ValueError as exc:
        await writer.event("error", payload={"code": "invalid_binary", "message": str(exc)})
        return
    if frame.kind is BinaryKind.PCM16 and len(frame.payload) > _MAX_PCM_FRAME_BYTES:
        await writer.event(
            "error",
            payload={
                "code": "invalid_pcm_frame",
                "message": "单个 PCM16 帧不能超过 200 毫秒",
            },
        )
        return
    if frame.kind is BinaryKind.PCM16:
        if budget is not None and not budget.accept_pcm(len(frame.payload)):
            await writer.event(
                "error",
                payload={
                    "code": "pcm_rate_limited",
                    "message": "PCM16 上传快于实时音频，已丢弃当前帧",
                },
            )
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
    session: StreamingAsrSession | None = None,
) -> None:
    if session is not None and update.epoch != session.epoch:
        return
    error = getattr(update, "error", None)
    if error is not None:
        code = _clean_identifier(getattr(error, "code", "")) or "asr_failed"
        message = str(getattr(error, "message", "") or "语音识别暂时不可用")
        await writer.event(
            "error",
            payload={"code": code, "message": message[:300]},
        )
        return
    final_monotonic_ns = time.monotonic_ns() if update.final and update.text else 0
    event_type = "asr.final" if update.final else "asr.partial"
    await writer.event(event_type, payload={"text": update.text})
    if session is not None and update.epoch != session.epoch:
        return
    if update.final and update.text:
        await turns.start_from_asr(
            update.text,
            final_monotonic_ns=final_monotonic_ns,
        )
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


async def _authenticate_realtime_handshake(
    websocket: WebSocket,
    services: AppServices,
    admission: AdmissionGate,
) -> RealtimeHandshake:
    """Resolve a server-authenticated actor before allocating tenant runtime state."""

    authenticator = services.realtime_authenticator
    identity_service = services.identity_service
    raw_session = websocket.query_params.get("session")
    if authenticator is not None and identity_service is not None:
        forbidden_query = {
            "user",
            "user_id",
            "userId",
            "token",
            "access_token",
            "accessToken",
        }
        if forbidden_query.intersection(websocket.query_params.keys()):
            raise RealtimeHandshakeError(4403, "identity query parameters are forbidden")
        token, credential_source = _realtime_access_token(
            websocket, services.realtime_access_cookie_name
        )
        if not token:
            raise RealtimeHandshakeError(4401, "authentication required")
        _validate_authenticated_realtime_origin(
            websocket,
            services.realtime_allowed_origins,
            cookie_authenticated=credential_source == "cookie",
        )
        try:
            principal = await asyncio.to_thread(authenticator, token)
        except (AuthenticationError, ValueError):
            raise RealtimeHandshakeError(4401, "invalid or expired authentication") from None
        if not isinstance(principal, AuthPrincipal):
            raise RealtimeHandshakeError(1011, "authentication service unavailable")
        if principal.expires_at_ms <= int(time.time() * 1000):
            raise RealtimeHandshakeError(4401, "invalid or expired authentication")
        try:
            session_id = (
                validate_session_hint(raw_session)
                if raw_session is not None
                else uuid.uuid4().hex
            )
            anima_id = AnimaId.parse(
                websocket.query_params.get("anima") or AnimaId.default().value
            )
        except InvalidIdentity:
            raise RealtimeHandshakeError(4403, "requested session is not available") from None
        lease = identity_service.active_anima_lease(principal.user_id, anima_id)
        try:
            await asyncio.to_thread(lease.__enter__)
        except CatalogError:
            raise RealtimeHandshakeError(4403, "requested Anima is not available") from None
        return RealtimeHandshake(
            session_id=session_id,
            identity=SessionIdentity(
                user_id=principal.user_id,
                anima_id=anima_id,
                anonymous=False,
                assurance="authenticated",
            ),
            anima_lease=lease,
            access_token=token,
            auth_session_id=principal.session_id,
            auth_expires_at_ms=principal.expires_at_ms,
        )

    if not services.allow_anonymous_realtime:
        raise RealtimeHandshakeError(4401, "authentication required")

    try:
        if services.admission.required:
            device_user = admission.device_identity(
                websocket.cookies.get(AdmissionGate.DEVICE_COOKIE_NAME)
            )
            if device_user is None:
                raise InvalidIdentity("设备会话无效")
            if websocket.query_params.get("user") is not None:
                raise InvalidIdentity("公网匿名会话的 user 身份由服务端签发")
            if websocket.query_params.get("anima") not in {None, "default"}:
                raise InvalidIdentity("公网匿名会话只能使用默认 Anima")
            return RealtimeHandshake(
                session_id=f"session_{device_user.removeprefix('device_')}",
                identity=SessionIdentity(
                    user_id=UserId.parse(device_user),
                    anima_id=AnimaId.default(),
                    anonymous=True,
                    assurance="admission_device",
                ),
            )
        session_id = (
            validate_session_hint(raw_session)
            if raw_session is not None
            else uuid.uuid4().hex
        )
        resolver = services.identity_resolver or _parse_session_identity
        identity = resolver(
            websocket.query_params.get("user"),
            websocket.query_params.get("anima"),
            session_id,
        )
        return RealtimeHandshake(session_id=session_id, identity=identity)
    except InvalidIdentity:
        raise RealtimeHandshakeError(4403, "requested session is not available") from None


def _realtime_access_token(
    websocket: WebSocket, cookie_name: str
) -> tuple[str, str]:
    cookie_token = str(websocket.cookies.get(cookie_name) or "").strip()
    authorization_values = websocket.headers.getlist("authorization")
    if len(authorization_values) > 1:
        return "", ""
    authorization = (
        str(authorization_values[0]).strip() if authorization_values else ""
    )
    header_token = ""
    if authorization:
        scheme, separator, credential = authorization.partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not credential.strip():
            return "", ""
        header_token = credential.strip()
    if cookie_token and header_token:
        return "", ""
    if header_token:
        return header_token, "bearer"
    if cookie_token:
        return cookie_token, "cookie"
    return "", ""


def _validate_authenticated_realtime_origin(
    websocket: WebSocket,
    allowed_origins: tuple[str, ...],
    *,
    cookie_authenticated: bool,
) -> None:
    origin = str(websocket.headers.get("origin") or "").strip().rstrip("/").lower()
    if cookie_authenticated and not origin:
        raise RealtimeHandshakeError(4403, "WebSocket Origin is required")
    if origin and origin not in allowed_origins:
        raise RealtimeHandshakeError(4403, "WebSocket Origin is not allowed")


def _parse_client_event(raw: str) -> dict[str, Any]:
    if len(raw) > _MAX_CONTROL_EVENT_CHARS:
        raise ValueError("控制事件超过 64 KiB")
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("事件必须是有效 JSON") from exc
    if not isinstance(event, dict) or event.get("v") != 2 or not isinstance(event.get("type"), str):
        raise ValueError("事件协议版本或类型无效")
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValueError("事件 payload 必须是对象")
    identity_fields = {
        "user",
        "userId",
        "user_id",
        "anima",
        "animaId",
        "anima_id",
    }
    if identity_fields.intersection(payload):
        raise InvalidIdentity("身份字段不能由客户端事件覆盖")
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
    if raw_anima_id is not None and AnimaId.parse(raw_anima_id) != AnimaId.default():
        raise InvalidIdentity("匿名会话只能使用默认 Anima；自定义角色需要服务端认证")
    user_id = UserId.anonymous_for(session_id)
    anima_id = AnimaId.default()
    return SessionIdentity(
        user_id=user_id,
        anima_id=anima_id,
        anonymous=True,
        assurance="anonymous_session_hint",
    )
