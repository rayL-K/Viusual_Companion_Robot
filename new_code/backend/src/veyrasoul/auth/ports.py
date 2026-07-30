"""认证端口将协议验证与领域会话管理隔离。"""

from __future__ import annotations

from typing import Protocol

from veyrasoul.identity import UserId

from .model import AuthPrincipal, VerifiedOidcIdentity


class OidcVerifier(Protocol):
    """由 OIDC SDK 实现；expected_nonce 必须来自服务端登录状态。"""

    def verify(
        self, id_token: str, expected_nonce: str
    ) -> VerifiedOidcIdentity: ...


class AuthRepository(Protocol):
    def resolve_user(self, identity: VerifiedOidcIdentity) -> UserId: ...

    def issue_session(
        self,
        user_id: UserId,
        oidc_issuer: str,
        token_hash: bytes,
        csrf_hash: bytes,
        now_ms: int,
        expires_at_ms: int,
        max_active_sessions: int,
    ) -> tuple[str, AuthPrincipal]: ...

    def authenticate(
        self, token_hash: bytes, csrf_hash: bytes | None, now_ms: int
    ) -> AuthPrincipal: ...

    def revoke(self, token_hash: bytes, now_ms: int) -> None: ...

    def cleanup_expired(self, now_ms: int) -> int: ...

    def rotate_session(
        self,
        old_token_hash: bytes,
        new_token_hash: bytes,
        new_csrf_hash: bytes,
        now_ms: int,
        expires_at_ms: int,
    ) -> tuple[str, AuthPrincipal]: ...
