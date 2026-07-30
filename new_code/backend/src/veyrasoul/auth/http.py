"""FastAPI 会话边界；统一处理 Cookie、Bearer 与 CSRF 约束。"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response, status

from .model import AuthenticationError, AuthPrincipal, CsrfValidationError, IssuedSession
from .service import AuthService


@dataclass(frozen=True, slots=True)
class SessionCookieConfig:
    access_cookie_name: str = "__Host-anima_session"
    csrf_cookie_name: str = "__Host-anima_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    same_site: str = "lax"

    def __post_init__(self) -> None:
        if self.same_site not in {"lax", "strict"}:
            raise ValueError("会话 Cookie SameSite 只能为 lax 或 strict")
        if not self.access_cookie_name.startswith(
            "__Host-"
        ) or not self.csrf_cookie_name.startswith("__Host-"):
            raise ValueError("会话 Cookie 必须使用 __Host- 前缀")
        for value in (
            self.access_cookie_name,
            self.csrf_cookie_name,
            self.csrf_header_name,
        ):
            if not value or any(character.isspace() for character in value):
                raise ValueError("Cookie 与 Header 名称无效")


class HttpSessionBoundary:
    def __init__(
        self,
        auth: AuthService,
        cookie_config: SessionCookieConfig = SessionCookieConfig(),
    ) -> None:
        self._auth = auth
        self._cookies = cookie_config

    @property
    def cookie_config(self) -> SessionCookieConfig:
        return self._cookies

    def set_session_cookies(
        self, response: Response, issued: IssuedSession
    ) -> None:
        max_age_seconds = (
            issued.principal.expires_at_ms - issued.principal.authenticated_at_ms
        ) // 1000
        if max_age_seconds <= 0:
            raise ValueError("会话有效期不足，无法设置 Cookie")
        common = {
            "secure": True,
            "samesite": self._cookies.same_site,
            "path": "/",
            "max_age": max_age_seconds,
        }
        response.set_cookie(
            self._cookies.access_cookie_name,
            issued.credentials.access_token,
            httponly=True,
            **common,
        )
        response.set_cookie(
            self._cookies.csrf_cookie_name,
            issued.credentials.csrf_token,
            httponly=False,
            **common,
        )

    def clear_session_cookies(self, response: Response) -> None:
        for name, http_only in (
            (self._cookies.access_cookie_name, True),
            (self._cookies.csrf_cookie_name, False),
        ):
            response.delete_cookie(
                name,
                path="/",
                secure=True,
                httponly=http_only,
                samesite=self._cookies.same_site,
            )

    def read_principal(self, request: Request) -> AuthPrincipal:
        try:
            access_token, _ = self._access_token(request)
            return self._auth.authenticate(access_token)
        except (AuthenticationError, ValueError) as exc:
            raise _unauthorized() from exc

    def mutation_principal(self, request: Request) -> AuthPrincipal:
        try:
            access_token, csrf_header = self._mutation_credentials(request)
            return self._auth.authenticate_mutation(access_token, csrf_header)
        except CsrfValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed",
            ) from exc
        except (AuthenticationError, ValueError) as exc:
            raise _unauthorized() from exc

    def rotate_session(
        self, request: Request, response: Response
    ) -> IssuedSession:
        try:
            access_token, csrf_token = self._mutation_credentials(request)
            issued = self._auth.rotate(access_token, csrf_token)
            self.set_session_cookies(response, issued)
            return issued
        except CsrfValidationError as exc:
            raise _forbidden_csrf() from exc
        except (AuthenticationError, ValueError) as exc:
            raise _unauthorized() from exc

    def revoke_session(self, request: Request, response: Response) -> None:
        try:
            access_token, csrf_token = self._mutation_credentials(request)
            self._auth.revoke_mutation(access_token, csrf_token)
            self.clear_session_cookies(response)
        except CsrfValidationError as exc:
            raise _forbidden_csrf() from exc
        except (AuthenticationError, ValueError) as exc:
            raise _unauthorized() from exc

    def _mutation_credentials(self, request: Request) -> tuple[str, str]:
        access_token, from_cookie = self._access_token(request)
        csrf_header = request.headers.get(self._cookies.csrf_header_name)
        if not csrf_header:
            raise CsrfValidationError("变更请求缺少 CSRF header")
        if from_cookie:
            csrf_cookie = request.cookies.get(self._cookies.csrf_cookie_name)
            if not csrf_cookie or not secrets.compare_digest(
                csrf_cookie, csrf_header
            ):
                raise CsrfValidationError("CSRF cookie 与 header 不匹配")
        return access_token, csrf_header

    def _access_token(self, request: Request) -> tuple[str, bool]:
        cookie_token = request.cookies.get(self._cookies.access_cookie_name)
        authorization_values = request.headers.getlist("Authorization")
        if len(authorization_values) > 1:
            raise AuthenticationError("Authorization 不得重复")
        authorization = authorization_values[0] if authorization_values else None
        if cookie_token and authorization:
            raise AuthenticationError("Cookie 与 Authorization 不得同时提供")
        if authorization:
            return _parse_bearer(authorization), False
        if cookie_token:
            return cookie_token, True
        raise AuthenticationError("缺少会话凭据")


def _parse_bearer(value: str) -> str:
    parts = value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise AuthenticationError("Authorization Bearer 格式无效")
    return parts[1]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden_csrf() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="CSRF validation failed",
    )
