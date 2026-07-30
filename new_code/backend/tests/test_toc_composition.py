from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from veyrasoul.auth import (
    SessionCookieConfig,
    SqliteAuthRepository,
    VerifiedOidcIdentity,
)
from veyrasoul.gateway.toc_composition import (
    TocConfigurationError,
    create_toc_composition,
)
from veyrasoul.identity import UserId
from veyrasoul.personalization import (
    DataLayout,
    IdentityService,
    SqliteIdentityRepository,
)


class StubVerifier:
    def verify(
        self, id_token: str, expected_nonce: str
    ) -> VerifiedOidcIdentity:
        assert id_token == "verified-id-token"
        assert expected_nonce == "expected-nonce"
        return VerifiedOidcIdentity(
            "https://issuer.example",
            "stable-subject",
            display_name=" Alice   Chen ",
        )


def dependencies(tmp_path):
    layout = DataLayout(tmp_path / "data", tmp_path / "legacy.db")
    identities = IdentityService(
        SqliteIdentityRepository(layout.identity_database()),
        layout,
        "默认人设",
    )
    auth = SqliteAuthRepository(tmp_path / "auth.sqlite3")
    return auth, identities


def document_factory(_user, _anima):
    raise AssertionError("composition tests do not execute document routes")


@pytest.mark.parametrize(
    "missing",
    (
        "oidc_verifier",
        "auth_repository",
        "identity_service",
        "document_ingestor_factory",
    ),
)
def test_incomplete_production_composition_fails_closed(tmp_path, missing) -> None:
    auth, identities = dependencies(tmp_path)
    arguments = {
        "oidc_verifier": StubVerifier(),
        "auth_repository": auth,
        "identity_service": identities,
        "document_ingestor_factory": document_factory,
    }
    arguments[missing] = None

    with pytest.raises(TocConfigurationError, match=missing):
        create_toc_composition(**arguments)


def test_first_oidc_login_provisions_once_and_reuses_stable_mapping(tmp_path) -> None:
    auth, identities = dependencies(tmp_path)
    composition = create_toc_composition(
        oidc_verifier=StubVerifier(),
        auth_repository=auth,
        identity_service=identities,
        document_ingestor_factory=document_factory,
    )

    first = composition.sign_in("verified-id-token", "expected-nonce")
    second = composition.sign_in("verified-id-token", "expected-nonce")

    assert first.principal.user_id == second.principal.user_id
    user = identities.get_user(first.principal.user_id)
    assert user.display_name == "Alice Chen"
    assert user.revision == 1


def test_concurrent_first_login_has_one_catalog_user(tmp_path) -> None:
    auth, identities = dependencies(tmp_path)
    composition = create_toc_composition(
        oidc_verifier=StubVerifier(),
        auth_repository=auth,
        identity_service=identities,
        document_ingestor_factory=document_factory,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        sessions = list(
            executor.map(
                lambda _: composition.sign_in(
                    "verified-id-token", "expected-nonce"
                ),
                range(8),
            )
        )

    user_ids = {session.principal.user_id for session in sessions}
    assert len(user_ids) == 1
    assert identities.get_user(next(iter(user_ids))).display_name == "Alice Chen"
    with sqlite3.connect(identities.repository.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_catalog_failure_never_issues_orphan_session_and_retry_recovers(
    tmp_path, monkeypatch
) -> None:
    auth, identities = dependencies(tmp_path)
    composition = create_toc_composition(
        oidc_verifier=StubVerifier(),
        auth_repository=auth,
        identity_service=identities,
        document_ingestor_factory=document_factory,
    )
    original_create = identities.create_user

    def fail_create(*_args, **_kwargs):
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(identities, "create_user", fail_create)
    with pytest.raises(RuntimeError, match="catalog unavailable"):
        composition.sign_in("verified-id-token", "expected-nonce")
    with sqlite3.connect(auth.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] == 0
        mapped_user = connection.execute(
            "SELECT user_id FROM auth_identities"
        ).fetchone()[0]

    monkeypatch.setattr(identities, "create_user", original_create)
    recovered = composition.sign_in("verified-id-token", "expected-nonce")
    assert recovered.principal.user_id.value == mapped_user
    assert identities.get_user(recovered.principal.user_id).display_name == "Alice Chen"


def test_session_issue_failure_leaves_catalog_but_no_usable_session(
    tmp_path, monkeypatch
) -> None:
    auth, identities = dependencies(tmp_path)
    composition = create_toc_composition(
        oidc_verifier=StubVerifier(),
        auth_repository=auth,
        identity_service=identities,
        document_ingestor_factory=document_factory,
    )

    def fail_issue(*_args, **_kwargs):
        raise RuntimeError("session store unavailable")

    monkeypatch.setattr(auth, "issue_session", fail_issue)
    with pytest.raises(RuntimeError, match="session store unavailable"):
        composition.sign_in("verified-id-token", "expected-nonce")

    with sqlite3.connect(auth.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] == 0
        mapped_user = connection.execute(
            "SELECT user_id FROM auth_identities"
        ).fetchone()[0]
    assert identities.get_user(UserId.parse(mapped_user)).display_name == "Alice Chen"


def test_rest_boundary_and_realtime_export_share_one_cookie_name(tmp_path) -> None:
    auth, identities = dependencies(tmp_path)
    cookies = SessionCookieConfig(
        access_cookie_name="__Host-custom_session",
        csrf_cookie_name="__Host-custom_csrf",
    )
    composition = create_toc_composition(
        oidc_verifier=StubVerifier(),
        auth_repository=auth,
        identity_service=identities,
        document_ingestor_factory=document_factory,
        cookie_config=cookies,
    )
    issued = composition.sign_in("verified-id-token", "expected-nonce")
    app = FastAPI()
    app.include_router(composition.router)
    client = TestClient(app, base_url="https://anima.example")

    # The exact exported name is what AppServices must use for WebSocket auth.
    assert composition.access_cookie_name == "__Host-custom_session"
    assert composition.session_boundary.cookie_config.access_cookie_name == (
        composition.access_cookie_name
    )
    client.cookies.set(
        composition.access_cookie_name,
        issued.credentials.access_token,
        path="/",
    )
    assert client.get("/v2/me").status_code == 200


def test_rest_rejects_bearer_cookie_conflict_and_enforces_double_submit_csrf(
    tmp_path,
) -> None:
    auth, identities = dependencies(tmp_path)
    composition = create_toc_composition(
        oidc_verifier=StubVerifier(),
        auth_repository=auth,
        identity_service=identities,
        document_ingestor_factory=document_factory,
    )
    issued = composition.sign_in("verified-id-token", "expected-nonce")
    app = FastAPI()
    app.include_router(composition.router)
    client = TestClient(app, base_url="https://anima.example")
    client.cookies.set(
        composition.cookie_config.access_cookie_name,
        issued.credentials.access_token,
        path="/",
    )

    conflict = client.get(
        "/v2/me", headers={"Authorization": "Bearer another-token"}
    )
    assert conflict.status_code == 401

    client.cookies.set(
        composition.cookie_config.csrf_cookie_name,
        issued.credentials.csrf_token,
        path="/",
    )
    mismatch = client.patch(
        "/v2/me",
        headers={
            composition.cookie_config.csrf_header_name: "different-token",
            "If-Match": '"1"',
        },
        json={"displayName": "Should Not Apply"},
    )
    assert mismatch.status_code == 403

    accepted = client.patch(
        "/v2/me",
        headers={
            composition.cookie_config.csrf_header_name: (
                issued.credentials.csrf_token
            ),
            "If-Match": '"1"',
        },
        json={"displayName": "Alice Updated"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["displayName"] == "Alice Updated"
