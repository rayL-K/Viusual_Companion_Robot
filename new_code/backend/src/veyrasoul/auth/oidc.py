"""基于 PyJWT 的标准 OIDC/JWKS 验证适配器。"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import jwt
from jwt import PyJWKClient

from .model import AuthenticationError, VerifiedOidcIdentity


_ASYMMETRIC_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
)


@dataclass(frozen=True, slots=True)
class OidcVerifierConfig:
    issuer: str
    audience: str
    client_id: str
    jwks_url: str
    allowed_algorithms: tuple[str, ...] = ("RS256",)
    leeway_seconds: int = 30
    jwks_cache_seconds: int = 300
    http_timeout_seconds: int = 5

    def __post_init__(self) -> None:
        for name, value in (
            ("audience", self.audience),
            ("client_id", self.client_id),
        ):
            if not value.strip():
                raise ValueError(f"OIDC {name} 不能为空")
        _validate_oidc_url("issuer", self.issuer)
        _validate_oidc_url("JWKS URL", self.jwks_url)
        if (
            not self.allowed_algorithms
            or set(self.allowed_algorithms) - _ASYMMETRIC_ALGORITHMS
        ):
            raise ValueError("OIDC 只允许显式配置的非对称签名算法")
        if not 0 <= self.leeway_seconds <= 300:
            raise ValueError("OIDC 时钟偏差必须在 0 至 300 秒之间")
        if not 30 <= self.jwks_cache_seconds <= 86_400:
            raise ValueError("JWKS 缓存时间必须在 30 秒至 24 小时之间")
        if not 1 <= self.http_timeout_seconds <= 30:
            raise ValueError("JWKS 请求超时必须在 1 至 30 秒之间")


class PyJwtOidcVerifier:
    """固定算法、签发方和受众，并利用 kid 未命中触发 JWKS 刷新。"""

    def __init__(
        self,
        config: OidcVerifierConfig,
        jwks_client_factory: Callable[..., PyJWKClient] = PyJWKClient,
    ) -> None:
        self._config = config
        self._jwks = jwks_client_factory(
            config.jwks_url,
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=config.jwks_cache_seconds,
            timeout=config.http_timeout_seconds,
        )

    def verify(
        self, id_token: str, expected_nonce: str
    ) -> VerifiedOidcIdentity:
        if not id_token or not expected_nonce:
            raise AuthenticationError("OIDC token 或 nonce 缺失")
        if len(id_token) > 65_536 or len(expected_nonce) > 512:
            raise AuthenticationError("OIDC token 或 nonce 超出长度限制")
        try:
            header = jwt.get_unverified_header(id_token)
            algorithm = header.get("alg")
            if algorithm not in self._config.allowed_algorithms:
                raise AuthenticationError("OIDC token 签名算法不受信")
            signing_key = self._jwks.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=list(self._config.allowed_algorithms),
                audience=self._config.audience,
                issuer=self._config.issuer,
                leeway=self._config.leeway_seconds,
                options={
                    "require": ["iss", "sub", "aud", "exp", "iat", "nonce"],
                    "verify_signature": True,
                    "verify_iss": True,
                    "verify_aud": True,
                    "verify_exp": True,
                    "verify_iat": True,
                },
            )
            _verify_nonce(claims, expected_nonce)
            _verify_authorized_party(claims, self._config.client_id)
            return _identity_from_claims(claims)
        except AuthenticationError:
            raise
        except jwt.PyJWTError as exc:
            raise AuthenticationError("OIDC token 验证失败") from exc
        except (TypeError, ValueError, KeyError) as exc:
            raise AuthenticationError("OIDC token claims 无效") from exc


def _verify_nonce(claims: dict[str, Any], expected_nonce: str) -> None:
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not secrets.compare_digest(nonce, expected_nonce):
        raise AuthenticationError("OIDC nonce 不匹配")


def _verify_authorized_party(
    claims: dict[str, Any], client_id: str
) -> None:
    audience = claims.get("aud")
    if isinstance(audience, list) and len(audience) > 1:
        authorized_party = claims.get("azp")
        if (
            not isinstance(authorized_party, str)
            or not secrets.compare_digest(authorized_party, client_id)
        ):
            raise AuthenticationError("OIDC 多受众 token 的 azp 无效")


def _identity_from_claims(claims: dict[str, Any]) -> VerifiedOidcIdentity:
    issuer = claims.get("iss")
    subject = claims.get("sub")
    if not isinstance(issuer, str) or not isinstance(subject, str):
        raise AuthenticationError("OIDC issuer 或 subject 无效")
    return VerifiedOidcIdentity(
        issuer=issuer,
        subject=subject,
        display_name=_optional_string(claims.get("name")),
        email=_optional_string(claims.get("email")),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _validate_oidc_url(name: str, value: str) -> None:
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
            f"OIDC {name} 必须是无 userinfo、query、fragment 的 HTTPS URL"
        )
