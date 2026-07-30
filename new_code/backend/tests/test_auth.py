from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from veyrasoul.auth import (
    AuthConfig,
    AuthenticationError,
    AuthService,
    CsrfValidationError,
    SqliteAuthRepository,
    VerifiedOidcIdentity,
)


class StubVerifier:
    def __init__(self, identities: dict[str, VerifiedOidcIdentity]) -> None:
        self.identities = identities

    def verify(
        self, id_token: str, expected_nonce: str
    ) -> VerifiedOidcIdentity:
        assert expected_nonce == "login-nonce"
        return self.identities[id_token]


def _service(
    tmp_path, now: list[int], *, max_active_sessions: int = 8
) -> AuthService:
    verifier = StubVerifier(
        {
            "alice-id-token": VerifiedOidcIdentity("https://id.example", "alice"),
            "bob-id-token": VerifiedOidcIdentity("https://id.example", "bob"),
        }
    )
    repository = SqliteAuthRepository(tmp_path / "auth.sqlite3")
    return AuthService(
        verifier,
        repository,
        AuthConfig(
            session_ttl_ms=60_000,
            max_active_sessions_per_user=max_active_sessions,
        ),
        clock_ms=lambda: now[0],
    )


def test_oidc_subject_maps_stably_and_users_are_isolated(tmp_path) -> None:
    now = [1_000_000]
    service = _service(tmp_path, now)

    alice = service.sign_in("alice-id-token", "login-nonce")
    alice_again = service.sign_in("alice-id-token", "login-nonce")
    bob = service.sign_in("bob-id-token", "login-nonce")

    assert alice.principal.user_id == alice_again.principal.user_id
    assert alice.principal.user_id != bob.principal.user_id
    assert service.authenticate(alice.credentials.access_token).user_id == alice.principal.user_id
    with pytest.raises(CsrfValidationError):
        service.authenticate_mutation(
            alice.credentials.access_token, bob.credentials.csrf_token
        )


def test_expired_and_revoked_sessions_are_rejected(tmp_path) -> None:
    now = [1_000_000]
    service = _service(tmp_path, now)
    issued = service.sign_in("alice-id-token", "login-nonce")

    now[0] = issued.credentials.expires_at_ms
    with pytest.raises(AuthenticationError, match="过期"):
        service.authenticate(issued.credentials.access_token)

    now[0] = 2_000_000
    active = service.sign_in("alice-id-token", "login-nonce")
    service.revoke_mutation(
        active.credentials.access_token, active.credentials.csrf_token
    )
    with pytest.raises(AuthenticationError, match="撤销"):
        service.authenticate(active.credentials.access_token)


def test_rotation_rejects_old_token_and_replay(tmp_path) -> None:
    now = [1_000_000]
    service = _service(tmp_path, now)
    original = service.sign_in("alice-id-token", "login-nonce")
    rotated = service.rotate(
        original.credentials.access_token, original.credentials.csrf_token
    )

    assert rotated.principal.user_id == original.principal.user_id
    with pytest.raises(AuthenticationError):
        service.authenticate(original.credentials.access_token)
    with pytest.raises(AuthenticationError):
        service.rotate(
            original.credentials.access_token, original.credentials.csrf_token
        )
    assert service.authenticate_mutation(
        rotated.credentials.access_token, rotated.credentials.csrf_token
    ) == rotated.principal


def test_concurrent_rotation_has_exactly_one_winner(tmp_path) -> None:
    now = [1_000_000]
    service = _service(tmp_path, now)
    original = service.sign_in("alice-id-token", "login-nonce")
    barrier = threading.Barrier(2)

    def rotate_once():
        barrier.wait()
        try:
            return service.rotate(
                original.credentials.access_token, original.credentials.csrf_token
            )
        except AuthenticationError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: rotate_once(), range(2)))

    winners = tuple(result for result in results if result is not None)
    assert len(winners) == 1
    assert service.authenticate(winners[0].credentials.access_token) == winners[0].principal
    with pytest.raises(AuthenticationError):
        service.authenticate(original.credentials.access_token)


def test_concurrent_sign_in_enforces_per_user_active_session_limit(tmp_path) -> None:
    now = [1_000_000]
    service = _service(tmp_path, now, max_active_sessions=2)

    with ThreadPoolExecutor(max_workers=6) as executor:
        issued = tuple(
            executor.map(
                lambda _: service.sign_in("alice-id-token", "login-nonce"),
                range(6),
            )
        )

    active = 0
    for session in issued:
        try:
            service.authenticate(session.credentials.access_token)
            active += 1
        except AuthenticationError:
            pass
    assert active == 2

    with sqlite3.connect(tmp_path / "auth.sqlite3") as connection:
        stored_active = connection.execute(
            "SELECT COUNT(*) FROM auth_sessions WHERE revoked_at_ms IS NULL"
        ).fetchone()[0]
    assert stored_active == 2


def test_cleanup_expired_removes_expired_rows(tmp_path) -> None:
    now = [1_000_000]
    service = _service(tmp_path, now)
    issued = service.sign_in("alice-id-token", "login-nonce")
    now[0] = issued.credentials.expires_at_ms

    assert service.cleanup_expired() == 1
    assert service.cleanup_expired() == 0
    with pytest.raises(AuthenticationError):
        service.authenticate(issued.credentials.access_token)


def test_revoke_requires_bound_csrf_token(tmp_path) -> None:
    now = [1_000_000]
    service = _service(tmp_path, now)
    alice = service.sign_in("alice-id-token", "login-nonce")
    bob = service.sign_in("bob-id-token", "login-nonce")

    with pytest.raises(CsrfValidationError):
        service.revoke_mutation(
            alice.credentials.access_token, bob.credentials.csrf_token
        )
    assert service.authenticate(alice.credentials.access_token) == alice.principal
    assert not hasattr(service, "revoke")


def test_database_and_reprs_do_not_leak_plaintext_credentials(tmp_path) -> None:
    now = [1_000_000]
    service = _service(tmp_path, now)
    issued = service.sign_in("alice-id-token", "login-nonce")
    access = issued.credentials.access_token
    csrf = issued.credentials.csrf_token

    assert access not in repr(issued)
    assert csrf not in repr(issued)
    database = tmp_path / "auth.sqlite3"
    assert access.encode() not in database.read_bytes()
    assert csrf.encode() not in database.read_bytes()

    with sqlite3.connect(database) as connection:
        token_hash, csrf_hash = connection.execute(
            "SELECT token_hash, csrf_hash FROM auth_sessions"
        ).fetchone()
    assert len(token_hash) == len(csrf_hash) == 32


def test_auth_migration_coexists_with_other_schema_versions(tmp_path) -> None:
    database = tmp_path / "shared.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=7")
        connection.execute("CREATE TABLE unrelated(value TEXT)")

    SqliteAuthRepository(database)
    SqliteAuthRepository(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
        assert connection.execute(
            "SELECT MAX(version) FROM auth_schema_versions"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='unrelated'"
        ).fetchone() is not None


def test_principal_cannot_be_selected_by_client_user_query(tmp_path) -> None:
    now = [1_000_000]
    service = _service(tmp_path, now)
    alice = service.sign_in("alice-id-token", "login-nonce")
    bob = service.sign_in("bob-id-token", "login-nonce")

    # 客户端即使携带其他 user_id，授权 actor 仍只由 bearer 会话产生。
    untrusted_query_user_id = bob.principal.user_id
    principal = service.authenticate(alice.credentials.access_token)
    assert principal.user_id != untrusted_query_user_id
