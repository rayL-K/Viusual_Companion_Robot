"""认证用例服务；所有 AuthPrincipal 均从服务端会话解析。"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from veyrasoul.identity import UserId

from .model import AuthPrincipal, IssuedSession, SessionCredentials
from .ports import AuthRepository, OidcVerifier


@dataclass(frozen=True, slots=True)
class AuthConfig:
    session_ttl_ms: int = 15 * 60 * 1000
    max_active_sessions_per_user: int = 8

    def __post_init__(self) -> None:
        if not 60_000 <= self.session_ttl_ms <= 24 * 60 * 60 * 1000:
            raise ValueError("会话有效期必须在 1 分钟至 24 小时之间")
        if not 1 <= self.max_active_sessions_per_user <= 100:
            raise ValueError("每用户最大活跃会话数必须在 1 至 100 之间")


class AuthService:
    def __init__(
        self,
        verifier: OidcVerifier,
        repository: AuthRepository,
        config: AuthConfig = AuthConfig(),
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._verifier = verifier
        self._repository = repository
        self._config = config
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    def sign_in(self, id_token: str) -> IssuedSession:
        if not id_token:
            raise ValueError("OIDC id_token 不能为空")
        identity = self._verifier.verify(id_token)
        user_id = self._repository.resolve_user(identity)
        return self._issue(user_id, identity.issuer)

    def authenticate(
        self, access_token: str, *, csrf_token: str | None = None
    ) -> AuthPrincipal:
        token_hash = _credential_hash(access_token, "access_token")
        csrf_hash = (
            _credential_hash(csrf_token, "csrf_token") if csrf_token is not None else None
        )
        return self._repository.authenticate(token_hash, csrf_hash, self._clock_ms())

    def authenticate_mutation(self, access_token: str, csrf_token: str) -> AuthPrincipal:
        return self.authenticate(access_token, csrf_token=csrf_token)

    def revoke_mutation(self, access_token: str, csrf_token: str) -> None:
        self.authenticate_mutation(access_token, csrf_token)
        self._repository.revoke(
            _credential_hash(access_token, "access_token"), self._clock_ms()
        )

    def cleanup_expired(self) -> int:
        return self._repository.cleanup_expired(self._clock_ms())

    def rotate(self, access_token: str, csrf_token: str) -> IssuedSession:
        now = self._clock_ms()
        current = self.authenticate_mutation(access_token, csrf_token)
        new_access = secrets.token_urlsafe(32)
        new_csrf = secrets.token_urlsafe(32)
        expires_at = now + self._config.session_ttl_ms
        _, principal = self._repository.rotate_session(
            _credential_hash(access_token, "access_token"),
            _credential_hash(new_access, "access_token"),
            _credential_hash(new_csrf, "csrf_token"),
            now,
            expires_at,
        )
        return IssuedSession(
            principal,
            SessionCredentials(new_access, new_csrf, expires_at),
        )

    def _issue(self, user_id: UserId, oidc_issuer: str) -> IssuedSession:
        now = self._clock_ms()
        expires_at = now + self._config.session_ttl_ms
        access_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        _, principal = self._repository.issue_session(
            user_id,
            oidc_issuer,
            _credential_hash(access_token, "access_token"),
            _credential_hash(csrf_token, "csrf_token"),
            now,
            expires_at,
            self._config.max_active_sessions_per_user,
        )
        return IssuedSession(
            principal,
            SessionCredentials(access_token, csrf_token, expires_at),
        )


def _credential_hash(value: str | None, name: str) -> bytes:
    if not value:
        raise ValueError(f"{name} 不能为空")
    domain = f"anima-auth:{name}:v1\0".encode("ascii")
    return hashlib.sha256(domain + value.encode("utf-8")).digest()
