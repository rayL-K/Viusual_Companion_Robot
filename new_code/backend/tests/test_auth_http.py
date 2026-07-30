from __future__ import annotations

from fastapi import Depends, FastAPI, Response
from fastapi.testclient import TestClient

from veyrasoul.auth import AuthPrincipal, IssuedSession, SessionCredentials
from veyrasoul.auth.http import HttpSessionBoundary
from veyrasoul.identity import UserId


ACCESS = "opaque-access-token"
CSRF = "bound-csrf-token"
PRINCIPAL = AuthPrincipal(
    UserId.parse("alice"),
    "session-1",
    1_000,
    61_000,
    "https://identity.example/",
)


class FakeAuth:
    def authenticate(self, access_token: str):
        assert access_token == ACCESS
        return PRINCIPAL

    def authenticate_mutation(self, access_token: str, csrf_token: str):
        assert access_token == ACCESS
        if csrf_token != CSRF:
            from veyrasoul.auth import CsrfValidationError

            raise CsrfValidationError("wrong csrf")
        return PRINCIPAL


def _client():
    boundary = HttpSessionBoundary(FakeAuth())
    app = FastAPI()

    @app.get("/read")
    def read(principal=Depends(boundary.read_principal)):
        return {"userId": principal.user_id.value}

    @app.post("/write")
    def write(principal=Depends(boundary.mutation_principal)):
        return {"userId": principal.user_id.value}

    @app.post("/cookies")
    def cookies(response: Response):
        boundary.set_session_cookies(
            response,
            IssuedSession(
                PRINCIPAL,
                SessionCredentials(ACCESS, CSRF, PRINCIPAL.expires_at_ms),
            ),
        )
        return {"ok": True}

    return TestClient(app)


def test_session_cookies_have_production_security_attributes() -> None:
    response = _client().post("/cookies")
    cookies = response.headers.get_list("set-cookie")

    access = next(value for value in cookies if "__Host-anima_session" in value)
    csrf = next(value for value in cookies if "__Host-anima_csrf" in value)
    assert "Secure" in access and "HttpOnly" in access
    assert "SameSite=lax" in access and "Path=/" in access
    assert "Secure" in csrf and "HttpOnly" not in csrf
    assert "SameSite=lax" in csrf and "Path=/" in csrf


def test_read_accepts_exactly_one_cookie_or_bearer_source() -> None:
    client = _client()
    assert client.get(
        "/read", headers={"Authorization": f"Bearer {ACCESS}"}
    ).status_code == 200

    conflict = client.get(
        "/read",
        headers={
            "Authorization": f"Bearer {ACCESS}",
            "Cookie": f"__Host-anima_session={ACCESS}",
        },
    )
    assert conflict.status_code == 401

    malformed = client.get(
        "/read", headers={"Authorization": f"Basic {ACCESS}"}
    )
    assert malformed.status_code == 401


def test_cookie_mutation_requires_matching_cookie_header_and_stored_csrf() -> None:
    client = _client()
    cookie_header = (
        f"__Host-anima_session={ACCESS}; __Host-anima_csrf={CSRF}"
    )

    assert client.post(
        "/write",
        headers={"Cookie": cookie_header, "X-CSRF-Token": CSRF},
    ).status_code == 200
    assert client.post(
        "/write", headers={"Cookie": cookie_header}
    ).status_code == 403
    assert client.post(
        "/write",
        headers={"Cookie": cookie_header, "X-CSRF-Token": "attacker"},
    ).status_code == 403
