"""Bounded anonymous admission for the public realtime gateway."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from veyrasoul.orchestration.ports import AsrAdmissionFailure


class WebSocketHandshake(Protocol):
    headers: object
    cookies: object
    client: object


@dataclass(frozen=True, slots=True)
class AdmissionPolicy:
    required: bool = False
    secret: str = field(default="", repr=False)
    turnstile_site_key: str = ""
    turnstile_secret: str = field(default="", repr=False)
    allowed_origins: tuple[str, ...] = ()
    token_ttl_seconds: int = 3_600
    device_ttl_seconds: int = 30 * 24 * 3_600
    max_connections: int = 12
    max_connections_per_client: int = 3
    max_concurrent_turns: int = 2
    max_turns_per_client_per_minute: int = 20
    max_turns_global_per_minute: int = 60
    max_concurrent_asr_requests: int = 2
    max_asr_requests_per_client_per_minute: int = 12
    max_asr_requests_global_per_minute: int = 48
    binary_bytes_per_second: int = 512 * 1024
    binary_burst_bytes: int = 2 * 1024 * 1024
    pcm_bytes_per_second: int = 16_000 * 2
    pcm_burst_bytes: int = 16_000 * 2
    control_events_per_second: int = 10
    control_burst_events: int = 20
    idle_timeout_seconds: int = 90
    max_session_seconds: int = 30 * 60

    def __post_init__(self) -> None:
        normalized = tuple(origin.rstrip("/").lower() for origin in self.allowed_origins)
        object.__setattr__(self, "allowed_origins", normalized)
        if self.required and len(self.secret.encode("utf-8")) < 32:
            raise ValueError("admission secret must contain at least 32 bytes")
        if self.required and not normalized:
            raise ValueError("required admission needs at least one allowed origin")
        if self.required and not self.turnstile_site_key.strip():
            raise ValueError("required admission needs a Turnstile site key")
        if self.required and not self.turnstile_secret.strip():
            raise ValueError("required admission needs a Turnstile secret")
        for name in (
            "token_ttl_seconds",
            "device_ttl_seconds",
            "max_connections",
            "max_connections_per_client",
            "max_concurrent_turns",
            "max_turns_per_client_per_minute",
            "max_turns_global_per_minute",
            "max_concurrent_asr_requests",
            "max_asr_requests_per_client_per_minute",
            "max_asr_requests_global_per_minute",
            "binary_bytes_per_second",
            "binary_burst_bytes",
            "pcm_bytes_per_second",
            "pcm_burst_bytes",
            "control_events_per_second",
            "control_burst_events",
            "idle_timeout_seconds",
            "max_session_seconds",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")
        if self.max_connections_per_client > self.max_connections:
            raise ValueError("per-client connection limit cannot exceed the global limit")
        if self.binary_burst_bytes < self.binary_bytes_per_second:
            raise ValueError("binary burst must be at least one second of the configured rate")
        if self.pcm_burst_bytes > self.pcm_bytes_per_second:
            raise ValueError("PCM burst must not exceed one second of the configured rate")
        if self.pcm_burst_bytes < 6_400:
            raise ValueError("PCM burst must accept at least one 200 millisecond frame")
        if self.control_burst_events < self.control_events_per_second:
            raise ValueError("control burst must be at least one second of the configured rate")
        if self.max_session_seconds < self.idle_timeout_seconds:
            raise ValueError("maximum session duration must be at least the idle timeout")


@dataclass(frozen=True, slots=True)
class AdmissionFailure:
    code: str
    reason: str
    close_code: int = 1008


class ConnectionBudget:
    def __init__(self, policy: AdmissionPolicy, client_key: str) -> None:
        self.client_key = client_key
        self._rate = float(policy.binary_bytes_per_second)
        self._capacity = float(policy.binary_burst_bytes)
        self._tokens = self._capacity
        self._updated_at = time.monotonic()
        self._control_rate = float(policy.control_events_per_second)
        self._control_capacity = float(policy.control_burst_events)
        self._control_tokens = self._control_capacity
        self._control_updated_at = time.monotonic()
        self._pcm_rate = float(policy.pcm_bytes_per_second)
        self._pcm_capacity = float(policy.pcm_burst_bytes)
        self._pcm_tokens = self._pcm_capacity
        self._pcm_updated_at = time.monotonic()

    def accept_binary(self, size: int, now: float | None = None) -> bool:
        amount = max(0, int(size))
        timestamp = time.monotonic() if now is None else float(now)
        elapsed = max(0.0, timestamp - self._updated_at)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._updated_at = timestamp
        if amount > self._tokens:
            return False
        self._tokens -= amount
        return True

    def accept_control(self, now: float | None = None) -> bool:
        timestamp = time.monotonic() if now is None else float(now)
        elapsed = max(0.0, timestamp - self._control_updated_at)
        self._control_tokens = min(
            self._control_capacity,
            self._control_tokens + elapsed * self._control_rate,
        )
        self._control_updated_at = timestamp
        if self._control_tokens < 1.0:
            return False
        self._control_tokens -= 1.0
        return True

    def accept_pcm(self, size: int, now: float | None = None) -> bool:
        """Limit mono 16 kHz PCM16 independently from JPEG/binary traffic."""

        amount = max(0, int(size))
        timestamp = time.monotonic() if now is None else float(now)
        elapsed = max(0.0, timestamp - self._pcm_updated_at)
        self._pcm_tokens = min(
            self._pcm_capacity,
            self._pcm_tokens + elapsed * self._pcm_rate,
        )
        self._pcm_updated_at = timestamp
        if amount > self._pcm_tokens:
            return False
        self._pcm_tokens -= amount
        return True


class ConnectionLease:
    def __init__(self, gate: "AdmissionGate", client_key: str, budget: ConnectionBudget) -> None:
        self._gate = gate
        self.client_key = client_key
        self.budget = budget
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._gate._release_connection(self.client_key)


class TurnLease:
    def __init__(self, gate: "AdmissionGate") -> None:
        self._gate = gate
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._gate._release_turn()


class AsrLease:
    def __init__(self, gate: "AdmissionGate") -> None:
        self._gate = gate
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._gate._release_asr()


class AdmissionGate:
    COOKIE_NAME = "anima_admission"
    DEVICE_COOKIE_NAME = "anima_device"

    def __init__(self, policy: AdmissionPolicy) -> None:
        self.policy = policy
        self._secret = policy.secret.encode("utf-8") if policy.secret else secrets.token_bytes(32)
        self._turnstile = TurnstileVerifier(policy)
        self._lock = asyncio.Lock()
        self._connections = 0
        self._connections_by_client: dict[str, int] = defaultdict(int)
        self._active_turns = 0
        self._global_turns: deque[float] = deque()
        self._turns_by_client: dict[str, deque[float]] = {}
        self._active_asr_requests = 0
        self._global_asr_requests: deque[float] = deque()
        self._asr_requests_by_client: dict[str, deque[float]] = {}

    def issue_token(self, now: int | None = None) -> str:
        return self._issue_signed_token("admission", now)

    def issue_device_token(self, now: int | None = None) -> str:
        return self._issue_signed_token("device", now)

    def _issue_signed_token(self, kind: str, now: int | None) -> str:
        issued_at = int(time.time() if now is None else now)
        payload = f"{issued_at}.{secrets.token_urlsafe(16)}"
        signature = hmac.new(
            self._secret,
            f"{kind}\0{payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{payload}.{_urlsafe(signature)}"

    def verify_token(self, token: object, now: int | None = None) -> bool:
        return self._verify_signed_token(
            "admission",
            token,
            self.policy.token_ttl_seconds,
            now,
        )

    def verify_device_token(self, token: object, now: int | None = None) -> bool:
        return self._verify_signed_token(
            "device",
            token,
            self.policy.device_ttl_seconds,
            now,
        )

    def _verify_signed_token(
        self,
        kind: str,
        token: object,
        ttl_seconds: int,
        now: int | None,
    ) -> bool:
        value = str(token or "")
        try:
            raw_timestamp, nonce, encoded_signature = value.split(".", 2)
            issued_at = int(raw_timestamp)
            signature = _urlsafe_decode(encoded_signature)
        except (TypeError, ValueError):
            return False
        if not nonce or len(nonce) > 128:
            return False
        current = int(time.time() if now is None else now)
        if issued_at > current + 30 or current - issued_at > ttl_seconds:
            return False
        payload = f"{raw_timestamp}.{nonce}"
        expected = hmac.new(
            self._secret,
            f"{kind}\0{payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        return hmac.compare_digest(signature, expected)

    def device_identity(self, token: object) -> str | None:
        value = str(token or "")
        if not self.verify_device_token(value):
            return None
        digest = hmac.new(
            self._secret,
            f"identity\0{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:24]
        return f"device_{digest}"

    async def verify_challenge(self, token: object, remote_ip: str) -> bool:
        return await self._turnstile.verify(str(token or ""), remote_ip)

    async def aclose(self) -> None:
        await self._turnstile.aclose()

    def validate_handshake(self, websocket: WebSocketHandshake) -> AdmissionFailure | None:
        if not self.policy.required:
            return None
        headers = websocket.headers  # Starlette Headers has case-insensitive get().
        origin = str(headers.get("origin") or "").rstrip("/").lower()
        if origin not in self.policy.allowed_origins:
            return AdmissionFailure("origin_denied", "WebSocket Origin 不在允许列表")
        token = websocket.cookies.get(self.COOKIE_NAME)
        if not self.verify_token(token):
            return AdmissionFailure(
                "admission_required",
                "请重新完成 Anima 连接校验",
                4401,
            )
        device_token = websocket.cookies.get(self.DEVICE_COOKIE_NAME)
        if not self.verify_device_token(device_token):
            return AdmissionFailure(
                "device_required",
                "设备会话已过期，请重新完成连接校验",
                4401,
            )
        return None

    async def try_connect(
        self,
        client_key: str,
    ) -> tuple[ConnectionLease | None, AdmissionFailure | None]:
        normalized = str(client_key or "unknown")[:128]
        async with self._lock:
            if self._connections >= self.policy.max_connections:
                return None, AdmissionFailure("server_busy", "实时连接已满，请稍后重试", 1013)
            if self._connections_by_client[normalized] >= self.policy.max_connections_per_client:
                return None, AdmissionFailure("connection_limited", "当前网络的实时连接过多", 1013)
            self._connections += 1
            self._connections_by_client[normalized] += 1
        return ConnectionLease(self, normalized, ConnectionBudget(self.policy, normalized)), None

    async def try_turn(
        self,
        connection: ConnectionLease,
        now: float | None = None,
    ) -> tuple[TurnLease | None, AdmissionFailure | None]:
        timestamp = time.monotonic() if now is None else float(now)
        cutoff = timestamp - 60.0
        async with self._lock:
            _prune(self._global_turns, cutoff)
            for key, values in tuple(self._turns_by_client.items()):
                _prune(values, cutoff)
                if not values:
                    self._turns_by_client.pop(key, None)
            client_turns = self._turns_by_client.get(connection.client_key)
            if client_turns is None:
                client_turns = deque()
            if len(client_turns) >= self.policy.max_turns_per_client_per_minute:
                return None, AdmissionFailure("turn_rate_limited", "对话太频繁，请稍后再试", 1013)
            if len(self._global_turns) >= self.policy.max_turns_global_per_minute:
                return None, AdmissionFailure("server_rate_limited", "Anima 正在忙，请稍后再试", 1013)
            if self._active_turns >= self.policy.max_concurrent_turns:
                return None, AdmissionFailure("server_busy", "Anima 正在回应其他请求，请稍后再试", 1013)
            self._turns_by_client[connection.client_key] = client_turns
            client_turns.append(timestamp)
            self._global_turns.append(timestamp)
            self._active_turns += 1
        return TurnLease(self), None

    async def _release_connection(self, client_key: str) -> None:
        async with self._lock:
            self._connections = max(0, self._connections - 1)
            count = self._connections_by_client.get(client_key, 0) - 1
            if count > 0:
                self._connections_by_client[client_key] = count
            else:
                self._connections_by_client.pop(client_key, None)

    async def _release_turn(self) -> None:
        async with self._lock:
            self._active_turns = max(0, self._active_turns - 1)

    async def try_asr(
        self,
        connection: ConnectionLease,
        now: float | None = None,
    ) -> tuple[AsrLease | None, AsrAdmissionFailure | None]:
        """Admit one paid ASR HTTP request without consuming turn quotas."""

        timestamp = time.monotonic() if now is None else float(now)
        cutoff = timestamp - 60.0
        async with self._lock:
            _prune(self._global_asr_requests, cutoff)
            for key, values in tuple(self._asr_requests_by_client.items()):
                _prune(values, cutoff)
                if not values:
                    self._asr_requests_by_client.pop(key, None)
            client_requests = self._asr_requests_by_client.get(connection.client_key)
            if client_requests is None:
                client_requests = deque()
            if (
                len(client_requests)
                >= self.policy.max_asr_requests_per_client_per_minute
            ):
                return None, AsrAdmissionFailure(
                    "asr_rate_limited",
                    "语音识别请求过于频繁，请稍后再试",
                )
            if (
                len(self._global_asr_requests)
                >= self.policy.max_asr_requests_global_per_minute
            ):
                return None, AsrAdmissionFailure(
                    "server_busy",
                    "语音识别服务繁忙，请稍后再试",
                )
            if self._active_asr_requests >= self.policy.max_concurrent_asr_requests:
                return None, AsrAdmissionFailure(
                    "server_busy",
                    "语音识别服务繁忙，请稍后再试",
                )
            self._asr_requests_by_client[connection.client_key] = client_requests
            client_requests.append(timestamp)
            self._global_asr_requests.append(timestamp)
            self._active_asr_requests += 1
        return AsrLease(self), None

    async def _release_asr(self) -> None:
        async with self._lock:
            self._active_asr_requests = max(0, self._active_asr_requests - 1)


def client_key(websocket: WebSocketHandshake) -> str:
    headers = websocket.headers
    forwarded = str(headers.get("cf-connecting-ip") or "").strip()
    if forwarded:
        return forwarded[:128]
    client = websocket.client
    return str(getattr(client, "host", "unknown") or "unknown")[:128]


class TurnstileVerifier:
    VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    ACTION = "anima_admission"

    def __init__(
        self,
        policy: AdmissionPolicy,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._enabled = policy.required
        self._secret = policy.turnstile_secret
        self._hostnames = {
            str(urlsplit(origin).hostname or "").lower()
            for origin in policy.allowed_origins
        }
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=2.0),
            transport=transport,
            # Admission secrets must go only to Cloudflare's fixed endpoint.
            # Ignore host proxy variables so a machine-wide proxy cannot
            # intercept Siteverify credentials or make startup environment-
            # dependent.
            trust_env=False,
        )

    async def verify(self, token: str, remote_ip: str = "") -> bool:
        value = token.strip()
        if not self._enabled or not value or len(value) > 2_048:
            return False
        form = {
            "secret": self._secret,
            "response": value,
            "idempotency_key": str(uuid.uuid4()),
        }
        if remote_ip:
            form["remoteip"] = remote_ip
        try:
            response = await self._client.post(self.VERIFY_URL, data=form)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return False
        if not isinstance(payload, dict) or payload.get("success") is not True:
            return False
        if str(payload.get("action") or "") != self.ACTION:
            return False
        return str(payload.get("hostname") or "").lower() in self._hostnames

    async def aclose(self) -> None:
        await self._client.aclose()


def _prune(values: deque[float], cutoff: float) -> None:
    while values and values[0] <= cutoff:
        values.popleft()


def _urlsafe(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
