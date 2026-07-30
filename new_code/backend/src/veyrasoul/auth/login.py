"""服务端 OIDC Authorization Code + PKCE 登录状态与交换流程。"""

from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .model import AuthenticationError, IssuedSession
from .schema import migrate


class LoginStateError(AuthenticationError):
    """登录 state 不存在、过期、已消费或密文无效。"""


class LoginCapacityError(LoginStateError):
    """全局未过期登录尝试已达到安全上限。"""


@dataclass(frozen=True, slots=True)
class LoginFlowConfig:
    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    attempt_ttl_ms: int = 5 * 60 * 1000
    max_unexpired_attempts: int = 1_000
    token_timeout_seconds: int = 10

    def __post_init__(self) -> None:
        for name, value in (
            ("authorization_endpoint", self.authorization_endpoint),
            ("token_endpoint", self.token_endpoint),
            ("redirect_uri", self.redirect_uri),
        ):
            parsed = urlparse(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    f"{name} 必须是无 userinfo、query、fragment 的固定 HTTPS URL"
                )
        if not self.client_id.strip():
            raise ValueError("OIDC client_id 不能为空")
        if "openid" not in self.scopes:
            raise ValueError("OIDC scopes 必须包含 openid")
        if not 60_000 <= self.attempt_ttl_ms <= 15 * 60 * 1000:
            raise ValueError("登录 state TTL 必须在 1 至 15 分钟之间")
        if not 1 <= self.max_unexpired_attempts <= 100_000:
            raise ValueError("全局未过期登录尝试上限必须在 1 至 100000 之间")
        if not 1 <= self.token_timeout_seconds <= 30:
            raise ValueError("OIDC token 请求超时必须在 1 至 30 秒之间")


@dataclass(frozen=True, slots=True)
class LoginRedirect:
    authorization_url: str
    expires_at_ms: int


@dataclass(frozen=True, slots=True)
class LoginAttempt:
    nonce: str
    code_verifier: str


class LoginAttemptStore(Protocol):
    def create(
        self,
        state: str,
        nonce: str,
        code_verifier: str,
        now_ms: int,
        expires_at_ms: int,
        max_unexpired_attempts: int = 1_000,
    ) -> None: ...

    def consume(self, state: str, now_ms: int) -> LoginAttempt: ...

    def cleanup_expired(self, now_ms: int) -> int: ...


class AuthorizationCodeExchanger(Protocol):
    def exchange(self, code: str, code_verifier: str) -> str: ...


class CompleteSignIn(Protocol):
    """必须指向包含用户建档的生产登录工作流。"""

    def __call__(
        self, id_token: str, expected_nonce: str
    ) -> IssuedSession: ...


class SqliteLoginAttemptStore:
    """仅持久化摘要与 Fernet 密文；密钥必须由进程外配置注入。"""

    def __init__(self, database_path: Path, encryption_key: bytes) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._cipher = Fernet(encryption_key)
        except (TypeError, ValueError) as exc:
            raise ValueError("登录状态加密密钥必须是有效 Fernet key") from exc
        self._lock = threading.RLock()
        with self._write() as connection:
            migrate(connection)

    def create(
        self,
        state: str,
        nonce: str,
        code_verifier: str,
        now_ms: int,
        expires_at_ms: int,
        max_unexpired_attempts: int = 1_000,
    ) -> None:
        if expires_at_ms <= now_ms:
            raise ValueError("登录 state 过期时间无效")
        if max_unexpired_attempts < 1:
            raise ValueError("全局未过期登录尝试上限必须大于零")
        with self._write() as connection:
            connection.execute(
                "DELETE FROM auth_login_attempts WHERE expires_at_ms<=?",
                (now_ms,),
            )
            unexpired = int(
                connection.execute(
                    "SELECT COUNT(*) FROM auth_login_attempts WHERE expires_at_ms>?",
                    (now_ms,),
                ).fetchone()[0]
            )
            if unexpired >= max_unexpired_attempts:
                raise LoginCapacityError("OIDC 登录尝试过多，请稍后重试")
            connection.execute(
                """
                INSERT INTO auth_login_attempts(
                    state_hash, nonce_hash, nonce_ciphertext, verifier_ciphertext,
                    created_at_ms, expires_at_ms
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    _digest("state", state),
                    _digest("nonce", nonce),
                    self._cipher.encrypt(nonce.encode("utf-8")),
                    self._cipher.encrypt(code_verifier.encode("ascii")),
                    now_ms,
                    expires_at_ms,
                ),
            )

    def consume(self, state: str, now_ms: int) -> LoginAttempt:
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM auth_login_attempts WHERE state_hash=?",
                (_digest("state", state),),
            ).fetchone()
            if row is None or row["consumed_at_ms"] is not None:
                raise LoginStateError("OIDC state 无效或已使用")
            if int(row["expires_at_ms"]) <= now_ms:
                raise LoginStateError("OIDC state 已过期")
            cursor = connection.execute(
                """
                UPDATE auth_login_attempts SET consumed_at_ms=?
                WHERE state_hash=? AND consumed_at_ms IS NULL
                """,
                (now_ms, row["state_hash"]),
            )
            if cursor.rowcount != 1:
                raise LoginStateError("OIDC state 已被并发消费")
        try:
            nonce = self._cipher.decrypt(row["nonce_ciphertext"]).decode("utf-8")
            verifier = self._cipher.decrypt(row["verifier_ciphertext"]).decode("ascii")
        except (InvalidToken, UnicodeError) as exc:
            raise LoginStateError("OIDC 登录状态密文无效") from exc
        if not secrets.compare_digest(_digest("nonce", nonce), row["nonce_hash"]):
            raise LoginStateError("OIDC nonce 完整性校验失败")
        return LoginAttempt(nonce=nonce, code_verifier=verifier)

    def cleanup_expired(self, now_ms: int) -> int:
        with self._write() as connection:
            cursor = connection.execute(
                "DELETE FROM auth_login_attempts WHERE expires_at_ms<=?",
                (now_ms,),
            )
        return cursor.rowcount

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = sqlite3.connect(str(self.database_path), timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()


class HttpxAuthorizationCodeExchanger:
    def __init__(
        self,
        config: LoginFlowConfig,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    def exchange(self, code: str, code_verifier: str) -> str:
        if not code or len(code) > 4096:
            raise LoginStateError("OIDC authorization code 无效")
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self._config.token_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    self._config.token_endpoint,
                    data={
                        "grant_type": "authorization_code",
                        "client_id": self._config.client_id,
                        "code": code,
                        "redirect_uri": self._config.redirect_uri,
                        "code_verifier": code_verifier,
                    },
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AuthenticationError("OIDC token 交换失败") from exc
        id_token = payload.get("id_token") if isinstance(payload, dict) else None
        if not isinstance(id_token, str) or not id_token:
            raise AuthenticationError("OIDC token 响应缺少 id_token")
        return id_token


class OidcLoginFlow:
    def __init__(
        self,
        config: LoginFlowConfig,
        store: LoginAttemptStore,
        exchanger: AuthorizationCodeExchanger,
        complete_sign_in: CompleteSignIn,
        clock_ms=None,
    ) -> None:
        self._config = config
        self._store = store
        self._exchanger = exchanger
        if not callable(complete_sign_in):
            raise ValueError("complete_sign_in 必须是包含用户建档的登录工作流")
        self._complete_sign_in = complete_sign_in
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    def begin(self) -> LoginRedirect:
        now = self._clock_ms()
        expires_at = now + self._config.attempt_ttl_ms
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        self._store.create(
            state,
            nonce,
            verifier,
            now,
            expires_at,
            self._config.max_unexpired_attempts,
        )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "scope": " ".join(self._config.scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": _pkce_challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
        return LoginRedirect(
            authorization_url=f"{self._config.authorization_endpoint}?{query}",
            expires_at_ms=expires_at,
        )

    def complete(self, code: str, state: str) -> IssuedSession:
        if not state or len(state) > 512:
            raise LoginStateError("OIDC state 无效")
        attempt = self._store.consume(state, self._clock_ms())
        id_token = self._exchanger.exchange(code, attempt.code_verifier)
        return self._complete_sign_in(id_token, attempt.nonce)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _digest(purpose: str, value: str) -> bytes:
    if not value:
        raise LoginStateError(f"OIDC {purpose} 不能为空")
    domain = f"anima-oidc:{purpose}:v1\0".encode("ascii")
    return hashlib.sha256(domain + value.encode("utf-8")).digest()
