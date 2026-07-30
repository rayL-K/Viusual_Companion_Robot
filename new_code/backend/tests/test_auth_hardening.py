from __future__ import annotations

import asyncio
import sqlite3

import pytest
from cryptography.fernet import Fernet
from starlette.requests import Request

from veyrasoul.auth import SqliteAuthRepository
from veyrasoul.auth.login import SqliteLoginAttemptStore
from veyrasoul.auth.maintenance import AuthExpiryMaintenance
from veyrasoul.auth.maintenance import PeriodicAuthExpiryMaintenance
from veyrasoul.auth.rate_limit import (
    LoginRateLimitConfig,
    LoginRateLimitExceeded,
    LoginRateLimiter,
)


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/auth/login",
            "raw_path": b"/auth/login",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 443),
            "server": ("anima.example", 443),
        }
    )


def test_untrusted_peer_cannot_rotate_x_forwarded_for_to_evade_limit() -> None:
    now = [1.0]
    limiter = LoginRateLimiter(
        LoginRateLimitConfig(per_client_limit=2, global_limit=10),
        clock=lambda: now[0],
    )
    limiter.check(_request("198.51.100.10", "203.0.113.1"))
    limiter.check(_request("198.51.100.10", "203.0.113.2"))

    with pytest.raises(LoginRateLimitExceeded):
        limiter.check(_request("198.51.100.10", "203.0.113.3"))


def test_trusted_proxy_uses_rightmost_untrusted_forwarded_address() -> None:
    limiter = LoginRateLimiter(
        LoginRateLimitConfig(
            per_client_limit=1,
            global_limit=10,
            trusted_proxy_cidrs=("10.0.0.0/8",),
        ),
        clock=lambda: 1.0,
    )
    limiter.check(_request("10.0.0.2", "203.0.113.1, 198.51.100.20"))

    with pytest.raises(LoginRateLimitExceeded):
        limiter.check(
            _request("10.0.0.2", "203.0.113.99, 198.51.100.20")
        )


def test_global_login_limit_applies_across_client_addresses() -> None:
    limiter = LoginRateLimiter(
        LoginRateLimitConfig(per_client_limit=2, global_limit=2),
        clock=lambda: 1.0,
    )
    limiter.check(_request("198.51.100.1"))
    limiter.check(_request("198.51.100.2"))

    with pytest.raises(LoginRateLimitExceeded, match="全局"):
        limiter.check(_request("198.51.100.3"))


def test_auth_sqlite_uses_wal_for_sessions_and_login_attempts(tmp_path) -> None:
    database = tmp_path / "auth.sqlite3"
    SqliteAuthRepository(database)
    SqliteLoginAttemptStore(database, Fernet.generate_key())

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


class CleanupStore:
    def __init__(self, deleted: int) -> None:
        self.deleted = deleted
        self.called_with = None

    def cleanup_expired(self, now_ms: int) -> int:
        self.called_with = now_ms
        return self.deleted


def test_auth_maintenance_cleans_both_stores_with_one_timestamp() -> None:
    sessions = CleanupStore(3)
    attempts = CleanupStore(5)
    maintenance = AuthExpiryMaintenance(
        sessions, attempts, clock_ms=lambda: 123_456
    )

    report = maintenance.run_once()

    assert report.expired_sessions == 3
    assert report.expired_login_attempts == 5
    assert report.total == 8
    assert sessions.called_with == attempts.called_with == 123_456


def test_periodic_auth_maintenance_is_owned_by_lifespan() -> None:
    async def scenario() -> None:
        sessions = CleanupStore(1)
        attempts = CleanupStore(1)
        worker = PeriodicAuthExpiryMaintenance(
            AuthExpiryMaintenance(sessions, attempts, clock_ms=lambda: 42),
            interval_seconds=60,
        )

        await worker.start()
        assert sessions.called_with == attempts.called_with == 42
        await worker.aclose()
        await worker.aclose()

    asyncio.run(scenario())
