"""可独立挂载的认证 Router，不持有主应用生命周期。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from .http import HttpSessionBoundary
from .login import LoginCapacityError, LoginStateError, OidcLoginFlow
from .model import AuthenticationError
from .rate_limit import LoginRateLimiter, LoginRateLimitExceeded


@dataclass(frozen=True, slots=True)
class AuthRouterConfig:
    prefix: str = "/auth"
    success_redirect_path: str = "/"

    def __post_init__(self) -> None:
        if not self.prefix.startswith("/") or "://" in self.prefix:
            raise ValueError("认证 Router prefix 必须是站内绝对路径")
        if (
            not self.success_redirect_path.startswith("/")
            or self.success_redirect_path.startswith("//")
            or "\\" in self.success_redirect_path
            or "://" in self.success_redirect_path
        ):
            raise ValueError("登录成功跳转必须是固定站内路径")


def create_auth_router(
    login_flow: OidcLoginFlow,
    sessions: HttpSessionBoundary,
    config: AuthRouterConfig = AuthRouterConfig(),
    rate_limiter: LoginRateLimiter | None = None,
) -> APIRouter:
    router = APIRouter(prefix=config.prefix, tags=["auth"])
    resolved_rate_limiter = rate_limiter or LoginRateLimiter()

    @router.get("/login", response_class=RedirectResponse)
    def login(request: Request) -> RedirectResponse:
        try:
            resolved_rate_limiter.check(request)
            attempt = login_flow.begin()
        except (LoginCapacityError, LoginRateLimitExceeded) as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many pending login attempts",
                headers={"Retry-After": "60"},
            ) from exc
        response = RedirectResponse(
            attempt.authorization_url,
            status_code=status.HTTP_302_FOUND,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/callback")
    def callback(
        code: Annotated[str, Query(min_length=1, max_length=4096)],
        state_value: Annotated[
            str, Query(alias="state", min_length=1, max_length=512)
        ],
    ) -> RedirectResponse:
        try:
            issued = login_flow.complete(code, state_value)
        except (AuthenticationError, LoginStateError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="OIDC callback rejected",
            ) from exc
        response = RedirectResponse(
            config.success_redirect_path,
            status_code=status.HTTP_303_SEE_OTHER,
        )
        sessions.set_session_cookies(response, issued)
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.post("/rotate")
    def rotate(request: Request, response: Response) -> dict[str, object]:
        issued = sessions.rotate_session(request, response)
        response.headers["Cache-Control"] = "no-store"
        return {
            "rotated": True,
            "expiresAtMs": issued.credentials.expires_at_ms,
        }

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        sessions.revoke_session(request, response)
        response.headers["Cache-Control"] = "no-store"
        return {"loggedOut": True}

    return router
