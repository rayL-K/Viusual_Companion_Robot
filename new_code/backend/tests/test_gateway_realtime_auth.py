from __future__ import annotations

import time
import sqlite3

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from veyrasoul.auth import AuthenticationError, AuthPrincipal
from veyrasoul.gateway import AppServices, create_app
from veyrasoul.gateway.app import RealtimeHandshake
from veyrasoul.identity import AnimaId, SessionIdentity, UserId
from veyrasoul.personalization import (
    DataLayout,
    IdentityService,
    SqliteIdentityRepository,
)


class _Llm:
    async def stream_reply(self, messages):
        del messages
        yield "你好。"


class _Tts:
    async def synthesize(self, request):
        del request
        return b"RIFF", "audio/wav"


def _identity_service(tmp_path) -> IdentityService:
    layout = DataLayout(tmp_path / "accounts", tmp_path / "legacy.db")
    service = IdentityService(
        SqliteIdentityRepository(layout.identity_database()),
        layout,
        "默认人设",
    )
    service.create_user(UserId("alice"), "Alice")
    service.create_user(UserId("bob"), "Bob")
    service.create_anima(UserId("alice"), AnimaId("rabbit"), "月兔")
    service.create_anima(UserId("bob"), AnimaId("fox"), "小狐")
    return service


def _principal(user: str, *, expired: bool = False) -> AuthPrincipal:
    now = int(time.time() * 1000)
    return AuthPrincipal(
        user_id=UserId(user),
        session_id=f"auth-{user}",
        authenticated_at_ms=now - 1_000,
        expires_at_ms=now - 1 if expired else now + 60_000,
        oidc_issuer="https://identity.example",
    )


def _app(tmp_path):
    identities = _identity_service(tmp_path)
    principals = {
        "alice-token": _principal("alice"),
        "bob-token": _principal("bob"),
        "expired-token": _principal("alice", expired=True),
    }

    def authenticate(token: str) -> AuthPrincipal:
        try:
            principal = principals[token]
        except KeyError:
            raise AuthenticationError("invalid token") from None
        if principal.expires_at_ms <= int(time.time() * 1000):
            raise AuthenticationError("expired token")
        return principal

    app = create_app(
        AppServices(
            memory_path=tmp_path / "legacy.db",
            data_root=tmp_path / "accounts",
            llm=_Llm(),
            tts=_Tts(),
            stable_system_prompt="稳定规则",
            realtime_authenticator=authenticate,
            identity_service=identities,
            realtime_allowed_origins=("https://anima.veyralux.org",),
            realtime_reauth_seconds=0.05,
            realtime_lease_renew_seconds=0.05,
        )
    )
    app.state.test_principals = principals
    return app, identities


def _authorization(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("url", "headers", "close_code"),
    (
        ("/v2/realtime?anima=rabbit", {}, 4401),
        (
            "/v2/realtime?anima=rabbit",
            {"authorization": "Bearer expired-token"},
            4401,
        ),
        (
            "/v2/realtime?anima=rabbit&user=bob",
            {"authorization": "Bearer alice-token"},
            4403,
        ),
        (
            "/v2/realtime?anima=fox",
            {"authorization": "Bearer alice-token"},
            4403,
        ),
        (
            "/v2/realtime?anima=missing",
            {"authorization": "Bearer alice-token"},
            4403,
        ),
    ),
)
def test_realtime_handshake_rejects_missing_expired_and_cross_tenant_identity(
    tmp_path, url, headers, close_code
) -> None:
    app, _ = _app(tmp_path)

    with pytest.raises(WebSocketDisconnect) as rejected:
        with TestClient(app).websocket_connect(url, headers=headers):
            pass

    assert rejected.value.code == close_code


def test_deleting_anima_is_rejected_before_runtime_creation(tmp_path) -> None:
    app, identities = _app(tmp_path)
    identities.request_anima_deletion(UserId("alice"), AnimaId("rabbit"), 1)

    with pytest.raises(WebSocketDisconnect) as rejected:
        with TestClient(app).websocket_connect(
            "/v2/realtime?anima=rabbit",
            headers=_authorization("alice-token"),
        ):
            pass

    assert rejected.value.code == 4403
    assert app.state.registry._sessions == {}


def test_authenticated_cookie_binds_principal_and_reconnects_same_session(tmp_path) -> None:
    app, _ = _app(tmp_path)
    headers = {
        "cookie": "__Host-anima_session=alice-token",
        "origin": "https://anima.veyralux.org",
    }
    url = "/v2/realtime?session=reconnect-1&anima=rabbit"

    with TestClient(app) as client:
        with client.websocket_connect(url, headers=headers) as first:
            ready = first.receive_json()
            assert ready["type"] == "session.ready"
            assert ready["sessionId"] == "reconnect-1"
            assert ready["payload"] == {
                "protocol": 2,
                "userId": "alice",
                "animaId": "rabbit",
                "anonymous": False,
                "identityAssurance": "authenticated",
            }
        with client.websocket_connect(url, headers=headers) as second:
            reconnected = second.receive_json()
            assert reconnected["sessionId"] == "reconnect-1"
            assert reconnected["payload"]["userId"] == "alice"
            assert reconnected["payload"]["animaId"] == "rabbit"

    assert len(app.state.registry._sessions) == 1


def test_client_event_cannot_replace_authenticated_identity(tmp_path) -> None:
    app, _ = _app(tmp_path)

    with TestClient(app).websocket_connect(
        "/v2/realtime?anima=rabbit",
        headers=_authorization("alice-token"),
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.ready"
        websocket.send_json(
            {
                "v": 2,
                "type": "session.hello",
                "payload": {"userId": "bob", "animaId": "fox"},
            }
        )
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["payload"]["code"] == "identity_forgery"
        with pytest.raises(WebSocketDisconnect) as rejected:
            websocket.receive_json()
        assert rejected.value.code == 1008


def test_realtime_is_fail_closed_without_auth_or_explicit_development_mode(
    tmp_path,
) -> None:
    app = create_app(
        AppServices(
            memory_path=tmp_path / "legacy.db",
            llm=_Llm(),
            tts=_Tts(),
            stable_system_prompt="稳定规则",
        )
    )

    with pytest.raises(WebSocketDisconnect) as rejected:
        with TestClient(app).websocket_connect("/v2/realtime"):
            pass

    assert rejected.value.code == 4401


def test_realtime_rejects_ambiguous_cookie_and_bearer_credentials(tmp_path) -> None:
    app, _ = _app(tmp_path)

    with pytest.raises(WebSocketDisconnect) as rejected:
        with TestClient(app).websocket_connect(
            "/v2/realtime?anima=rabbit",
            headers={
                "authorization": "Bearer alice-token",
                "cookie": "__Host-anima_session=alice-token",
            },
        ):
            pass

    assert rejected.value.code == 4401


@pytest.mark.parametrize(
    "headers",
    (
        {
            "cookie": "__Host-anima_session=alice-token",
            "origin": "https://evil.veyralux.org",
        },
        {
            "authorization": "Bearer alice-token",
            "origin": "https://evil.example",
        },
        {"cookie": "__Host-anima_session=alice-token"},
    ),
)
def test_authenticated_realtime_rejects_malicious_or_missing_browser_origin(
    tmp_path, headers
) -> None:
    app, _ = _app(tmp_path)

    with pytest.raises(WebSocketDisconnect) as rejected:
        with TestClient(app).websocket_connect(
            "/v2/realtime?anima=rabbit",
            headers=headers,
        ):
            pass

    assert rejected.value.code == 4403


def test_bearer_non_browser_client_may_omit_origin(tmp_path) -> None:
    app, _ = _app(tmp_path)

    with TestClient(app).websocket_connect(
        "/v2/realtime?anima=rabbit",
        headers={"authorization": "Bearer alice-token"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.ready"


def test_realtime_handshake_repr_never_contains_access_token() -> None:
    handshake = RealtimeHandshake(
        session_id="session",
        identity=SessionIdentity(
            user_id=UserId("alice"),
            anima_id=AnimaId("rabbit"),
            anonymous=False,
            assurance="authenticated",
        ),
        access_token="super-secret-access-token",
        auth_session_id="auth-session",
    )

    assert "super-secret-access-token" not in repr(handshake)


def test_realtime_closes_after_session_is_revoked(tmp_path) -> None:
    app, _ = _app(tmp_path)

    with TestClient(app).websocket_connect(
        "/v2/realtime?anima=rabbit",
        headers={"authorization": "Bearer alice-token"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.ready"
        del app.state.test_principals["alice-token"]
        with pytest.raises(WebSocketDisconnect) as rejected:
            websocket.receive_json()

    assert rejected.value.code == 4401


def test_realtime_renews_active_anima_lease(tmp_path) -> None:
    app, identities = _app(tmp_path)
    database = identities.repository.database_path

    with TestClient(app).websocket_connect(
        "/v2/realtime?anima=rabbit",
        headers={"authorization": "Bearer alice-token"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.ready"
        with sqlite3.connect(database) as connection:
            before = connection.execute(
                "SELECT expires_at_ms FROM active_anima_leases"
            ).fetchone()[0]
        time.sleep(0.08)
        websocket.send_json(
            {"v": 2, "type": "session.heartbeat", "payload": {}}
        )
        assert websocket.receive_json()["type"] == "session.heartbeat.ack"
        with sqlite3.connect(database) as connection:
            after = connection.execute(
                "SELECT expires_at_ms FROM active_anima_leases"
            ).fetchone()[0]

    assert after > before


def test_realtime_closes_when_anima_lease_cannot_be_renewed(tmp_path) -> None:
    app, identities = _app(tmp_path)

    with TestClient(app).websocket_connect(
        "/v2/realtime?anima=rabbit",
        headers={"authorization": "Bearer alice-token"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.ready"
        with sqlite3.connect(identities.repository.database_path) as connection:
            connection.execute("DELETE FROM active_anima_leases")
        with pytest.raises(WebSocketDisconnect) as rejected:
            websocket.receive_json()

    assert rejected.value.code == 4403
