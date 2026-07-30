from __future__ import annotations

import sqlite3
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from veyrasoul.auth import SqliteAuthRepository, VerifiedOidcIdentity
from veyrasoul.auth.login import LoginFlowConfig, SqliteLoginAttemptStore
from veyrasoul.auth.routes import create_auth_router
from veyrasoul.gateway.toc_composition import (
    create_toc_composition,
    create_toc_oidc_login_flow,
)
from veyrasoul.personalization import (
    DataLayout,
    IdentityService,
    SqliteIdentityRepository,
)


class ProvisioningVerifier:
    def verify(self, id_token: str, expected_nonce: str):
        assert id_token == "provider-id-token"
        assert expected_nonce
        return VerifiedOidcIdentity(
            "https://identity.example/",
            "first-login-subject",
            display_name="First User",
        )


class TokenExchanger:
    def exchange(self, code: str, code_verifier: str) -> str:
        assert code == "authorization-code"
        assert code_verifier
        return "provider-id-token"


def _composition(tmp_path):
    layout = DataLayout(tmp_path / "data", tmp_path / "legacy.db")
    identities = IdentityService(
        SqliteIdentityRepository(layout.identity_database()),
        layout,
        "默认人设",
    )
    auth_repository = SqliteAuthRepository(tmp_path / "auth.sqlite3")
    composition = create_toc_composition(
        oidc_verifier=ProvisioningVerifier(),
        auth_repository=auth_repository,
        identity_service=identities,
        document_ingestor_factory=lambda _user, _anima: None,
    )
    flow = create_toc_oidc_login_flow(
        composition,
        LoginFlowConfig(
            authorization_endpoint="https://identity.example/authorize",
            token_endpoint="https://identity.example/token",
            client_id="anima-web",
            redirect_uri="https://anima.example/auth/callback",
        ),
        SqliteLoginAttemptStore(
            tmp_path / "auth.sqlite3", Fernet.generate_key()
        ),
        TokenExchanger(),
        clock_ms=lambda: 1_000_000,
    )
    app = FastAPI()
    app.include_router(create_auth_router(flow, composition.session_boundary))
    app.include_router(composition.router)
    return composition, flow, TestClient(
        app, base_url="https://anima.example", raise_server_exceptions=False
    )


def _begin_state(flow) -> str:
    query = parse_qs(urlparse(flow.begin().authorization_url).query)
    return query["state"][0]


def test_first_callback_provisions_catalog_before_cookie_and_me_is_ready(
    tmp_path,
) -> None:
    composition, flow, client = _composition(tmp_path)
    state = _begin_state(flow)

    callback = client.get(
        f"/auth/callback?code=authorization-code&state={state}",
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert "__Host-anima_session" in callback.headers.get("set-cookie", "")
    me = client.get("/v2/me")
    assert me.status_code == 200
    assert me.json()["displayName"] == "First User"
    assert composition.identity_service.get_user(
        composition.auth_service.authenticate(
            client.cookies.get("__Host-anima_session")
        ).user_id
    ).display_name == "First User"


def test_provisioning_failure_issues_no_session_or_cookie(
    tmp_path, monkeypatch
) -> None:
    composition, flow, client = _composition(tmp_path)

    def fail_provisioning(*_args) -> None:
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(
        composition.identity_service,
        "create_user",
        fail_provisioning,
    )
    state = _begin_state(flow)

    callback = client.get(
        f"/auth/callback?code=authorization-code&state={state}",
        follow_redirects=False,
    )

    assert callback.status_code == 500
    assert "__Host-anima_session" not in callback.headers.get("set-cookie", "")
    assert client.cookies.get("__Host-anima_session") is None
    with sqlite3.connect(tmp_path / "auth.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM auth_sessions"
        ).fetchone()[0] == 0
