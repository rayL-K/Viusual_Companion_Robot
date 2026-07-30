from __future__ import annotations

import base64
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from veyrasoul.auth import (
    AuthPrincipal,
    IssuedSession,
    SessionCredentials,
)
from veyrasoul.auth.http import HttpSessionBoundary
from veyrasoul.auth.login import (
    HttpxAuthorizationCodeExchanger,
    LoginFlowConfig,
    LoginRedirect,
    LoginCapacityError,
    LoginStateError,
    OidcLoginFlow,
    SqliteLoginAttemptStore,
)
from veyrasoul.auth.routes import create_auth_router
from veyrasoul.auth.rate_limit import (
    LoginRateLimitConfig,
    LoginRateLimiter,
)
from veyrasoul.identity import UserId


FLOW_CONFIG = LoginFlowConfig(
    authorization_endpoint="https://identity.example/authorize",
    token_endpoint="https://identity.example/token",
    client_id="anima-web",
    redirect_uri="https://anima.example/auth/callback",
)
PRINCIPAL = AuthPrincipal(
    UserId.parse("alice"),
    "session",
    1_000_000,
    1_900_000,
    "https://identity.example/",
)
ISSUED = IssuedSession(
    PRINCIPAL,
    SessionCredentials("access-token", "csrf-token", PRINCIPAL.expires_at_ms),
)


def _store(tmp_path):
    return SqliteLoginAttemptStore(
        tmp_path / "auth.sqlite3", Fernet.generate_key()
    )


def test_login_attempt_is_encrypted_at_rest_and_single_use(tmp_path) -> None:
    store = _store(tmp_path)
    store.create("browser-state", "server-nonce", "pkce-verifier", 1_000, 61_000)

    database_bytes = (tmp_path / "auth.sqlite3").read_bytes()
    assert b"browser-state" not in database_bytes
    assert b"server-nonce" not in database_bytes
    assert b"pkce-verifier" not in database_bytes
    assert store.consume("browser-state", 2_000).nonce == "server-nonce"
    with pytest.raises(LoginStateError):
        store.consume("browser-state", 2_001)


def test_expired_state_is_rejected_and_cleanup_removes_it(tmp_path) -> None:
    store = _store(tmp_path)
    store.create("expired-state", "nonce", "verifier", 1_000, 61_000)

    with pytest.raises(LoginStateError, match="过期"):
        store.consume("expired-state", 61_000)
    assert store.cleanup_expired(61_000) == 1


def test_concurrent_state_consumption_has_one_winner(tmp_path) -> None:
    store = _store(tmp_path)
    store.create("one-shot", "nonce", "verifier", 1_000, 61_000)

    def consume_once():
        try:
            return store.consume("one-shot", 2_000)
        except LoginStateError:
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = tuple(executor.map(lambda _: consume_once(), range(4)))
    assert sum(result is not None for result in results) == 1


class CapturingStore:
    def __init__(self) -> None:
        self.saved = None

    def create(
        self,
        state,
        nonce,
        verifier,
        now_ms,
        expires_at_ms,
        max_unexpired_attempts=1_000,
    ):
        self.saved = (state, nonce, verifier, now_ms, expires_at_ms)

    def consume(self, state, now_ms):
        assert self.saved is not None and state == self.saved[0]
        from veyrasoul.auth.login import LoginAttempt

        return LoginAttempt(self.saved[1], self.saved[2])

    def cleanup_expired(self, now_ms):
        return 0


class CapturingExchanger:
    def __init__(self) -> None:
        self.exchange_args = None

    def exchange(self, code, verifier):
        self.exchange_args = (code, verifier)
        return "verified-later-by-oidc-adapter"


class CapturingAuth:
    def __init__(self) -> None:
        self.sign_in_args = None

    def sign_in(self, token, expected_nonce):
        self.sign_in_args = (token, expected_nonce)
        return ISSUED


def test_flow_generates_s256_and_uses_server_saved_nonce() -> None:
    store = CapturingStore()
    exchanger = CapturingExchanger()
    auth = CapturingAuth()
    flow = OidcLoginFlow(
        FLOW_CONFIG, store, exchanger, auth.sign_in, clock_ms=lambda: 1_000
    )

    redirect = flow.begin()
    query = parse_qs(urlparse(redirect.authorization_url).query)
    state, nonce, verifier, _, _ = store.saved
    expected_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    assert query["state"] == [state]
    assert query["nonce"] == [nonce]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [expected_challenge]
    assert query["redirect_uri"] == [FLOW_CONFIG.redirect_uri]

    assert flow.complete("authorization-code", state) == ISSUED
    assert exchanger.exchange_args == ("authorization-code", verifier)
    assert auth.sign_in_args == ("verified-later-by-oidc-adapter", nonce)


def test_token_exchange_always_uses_configured_redirect_uri() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(parse_qs(request.content.decode("ascii")))
        return httpx.Response(200, json={"id_token": "signed-id-token"})

    exchanger = HttpxAuthorizationCodeExchanger(
        FLOW_CONFIG, transport=httpx.MockTransport(handler)
    )
    assert exchanger.exchange("code", "verifier") == "signed-id-token"
    assert captured["redirect_uri"] == [FLOW_CONFIG.redirect_uri]
    assert captured["code_verifier"] == ["verifier"]
    assert "https://evil.example/callback" not in captured.values()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authorization_endpoint", "https://user@identity.example/authorize"),
        ("authorization_endpoint", "https://identity.example/authorize?x=1"),
        ("token_endpoint", "https://identity.example/token#fragment"),
        ("redirect_uri", "https://user:pass@anima.example/auth/callback"),
        ("redirect_uri", "https://anima.example/auth/callback?next=/admin"),
    ],
)
def test_login_flow_urls_reject_userinfo_query_and_fragment(
    field, value
) -> None:
    values = {
        "authorization_endpoint": FLOW_CONFIG.authorization_endpoint,
        "token_endpoint": FLOW_CONFIG.token_endpoint,
        "client_id": FLOW_CONFIG.client_id,
        "redirect_uri": FLOW_CONFIG.redirect_uri,
    }
    values[field] = value

    with pytest.raises(ValueError):
        LoginFlowConfig(**values)


class RouterFlow:
    def __init__(
        self, *, fail_callback: bool = False, capacity_error: bool = False
    ) -> None:
        self.fail_callback = fail_callback
        self.capacity_error = capacity_error

    def begin(self):
        if self.capacity_error:
            raise LoginCapacityError("full")
        return LoginRedirect(
            "https://identity.example/authorize?redirect_uri="
            "https%3A%2F%2Fanima.example%2Fauth%2Fcallback",
            61_000,
        )

    def complete(self, code, state):
        if self.fail_callback:
            raise LoginStateError("invalid state")
        return ISSUED


class RouterAuth:
    def __init__(self) -> None:
        self.revoked = False

    def authenticate(self, access):
        return PRINCIPAL

    def authenticate_mutation(self, access, csrf):
        return PRINCIPAL

    def rotate(self, access, csrf):
        return ISSUED

    def revoke_mutation(self, access, csrf):
        self.revoked = True


def _router_client(flow=None, rate_limiter=None):
    auth = RouterAuth()
    sessions = HttpSessionBoundary(auth)
    app = FastAPI()
    app.include_router(
        create_auth_router(
            flow or RouterFlow(), sessions, rate_limiter=rate_limiter
        )
    )
    return TestClient(app), auth


def test_router_callback_sets_cookie_and_rejects_bad_callback() -> None:
    client, _ = _router_client()
    callback = client.get(
        "/auth/callback?code=ok&state=valid", follow_redirects=False
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/"
    assert "__Host-anima_session" in callback.headers.get("set-cookie", "")

    rejected, _ = _router_client(RouterFlow(fail_callback=True))
    response = rejected.get("/auth/callback?code=bad&state=bad")
    assert response.status_code == 401
    assert "invalid state" not in response.text


def test_login_has_no_open_redirect_and_logout_requires_csrf() -> None:
    client, auth = _router_client()
    login = client.get(
        "/auth/login?redirect_uri=https://evil.example/callback",
        follow_redirects=False,
    )
    assert login.status_code == 302
    assert "evil.example" not in login.headers["location"]

    cookie = "__Host-anima_session=access-token; __Host-anima_csrf=csrf-token"
    rotated = client.post(
        "/auth/rotate",
        headers={"Cookie": cookie, "X-CSRF-Token": "csrf-token"},
    )
    assert rotated.status_code == 200
    assert "__Host-anima_session" in rotated.headers.get("set-cookie", "")

    assert client.post("/auth/logout", headers={"Cookie": cookie}).status_code == 403
    logout = client.post(
        "/auth/logout",
        headers={"Cookie": cookie, "X-CSRF-Token": "csrf-token"},
    )
    assert logout.status_code == 200
    assert auth.revoked is True
    assert "Max-Age=0" in logout.headers.get("set-cookie", "")


def test_login_attempt_limit_cleans_expired_and_router_returns_429(tmp_path) -> None:
    store = _store(tmp_path)
    store.create("expired", "nonce-1", "verifier-1", 1_000, 61_000, 1)
    store.create("replacement", "nonce-2", "verifier-2", 61_000, 121_000, 1)
    with pytest.raises(LoginCapacityError):
        store.create("overflow", "nonce-3", "verifier-3", 61_001, 121_001, 1)

    with sqlite3.connect(tmp_path / "auth.sqlite3") as connection:
        states = connection.execute(
            "SELECT COUNT(*) FROM auth_login_attempts"
        ).fetchone()[0]
    assert states == 1

    client, _ = _router_client(RouterFlow(capacity_error=True))
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_login_route_enforces_rate_limiter_before_creating_attempt() -> None:
    limiter = LoginRateLimiter(
        LoginRateLimitConfig(per_client_limit=1, global_limit=2),
        clock=lambda: 1.0,
    )
    client, _ = _router_client(rate_limiter=limiter)

    assert client.get("/auth/login", follow_redirects=False).status_code == 302
    limited = client.get("/auth/login", follow_redirects=False)
    assert limited.status_code == 429
