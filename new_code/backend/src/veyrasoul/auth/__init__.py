"""ToC 认证领域公开接口。"""

from .http import HttpSessionBoundary, SessionCookieConfig
from .model import (
    AuthenticationError,
    AuthPrincipal,
    CsrfValidationError,
    IssuedSession,
    SessionCredentials,
    VerifiedOidcIdentity,
)
from .ports import AuthRepository, OidcVerifier
from .repository import SqliteAuthRepository
from .service import AuthConfig, AuthService

__all__ = [
    "AuthConfig",
    "AuthPrincipal",
    "AuthRepository",
    "AuthService",
    "AuthenticationError",
    "CsrfValidationError",
    "IssuedSession",
    "HttpSessionBoundary",
    "OidcVerifier",
    "SessionCredentials",
    "SessionCookieConfig",
    "SqliteAuthRepository",
    "VerifiedOidcIdentity",
]
