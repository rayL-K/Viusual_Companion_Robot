"""认证领域值对象；明文凭据只存在于一次性返回值中。"""

from __future__ import annotations

from dataclasses import dataclass, field

from veyrasoul.identity import UserId


class AuthenticationError(RuntimeError):
    """认证凭据无效、过期、撤销或已被轮换。"""


class CsrfValidationError(AuthenticationError):
    """CSRF 令牌未与当前会话绑定。"""


@dataclass(frozen=True, slots=True)
class VerifiedOidcIdentity:
    """由受信 OIDC 适配器验证后的最小身份，不接受原始 JWT claims。"""

    issuer: str
    subject: str
    display_name: str | None = None
    email: str | None = None

    def __post_init__(self) -> None:
        if not self.issuer.strip() or len(self.issuer) > 2048:
            raise ValueError("OIDC issuer 无效")
        if not self.subject.strip() or len(self.subject) > 512:
            raise ValueError("OIDC subject 无效")


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    """后端授权所需的可信 actor；只能由已验证会话构造。"""

    user_id: UserId
    session_id: str
    authenticated_at_ms: int
    expires_at_ms: int
    oidc_issuer: str


@dataclass(frozen=True, slots=True)
class SessionCredentials:
    """仅返回给调用方一次；repr 不得泄漏 bearer 或 CSRF 明文。"""

    access_token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    expires_at_ms: int

    def __post_init__(self) -> None:
        if not self.access_token or not self.csrf_token:
            raise ValueError("会话凭据不能为空")


@dataclass(frozen=True, slots=True)
class IssuedSession:
    principal: AuthPrincipal
    credentials: SessionCredentials
