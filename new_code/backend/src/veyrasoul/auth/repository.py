"""SQLite 认证仓储；会话轮换与旧令牌撤销保持原子性。"""

from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from veyrasoul.identity import UserId

from .model import (
    AuthenticationError,
    AuthPrincipal,
    CsrfValidationError,
    VerifiedOidcIdentity,
)
from .schema import migrate


class SqliteAuthRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._write() as connection:
            migrate(connection)

    def resolve_user(self, identity: VerifiedOidcIdentity) -> UserId:
        issuer = identity.issuer.strip()
        subject = identity.subject.strip()
        with self._write() as connection:
            row = connection.execute(
                "SELECT user_id FROM auth_identities WHERE issuer=? AND subject=?",
                (issuer, subject),
            ).fetchone()
            if row is not None:
                return UserId.parse(row["user_id"])
            user_id = UserId(f"usr_{secrets.token_hex(16)}")
            connection.execute(
                """
                INSERT INTO auth_identities(issuer, subject, user_id, created_at_ms)
                VALUES(?, ?, ?, ?)
                """,
                (issuer, subject, user_id.value, time.time_ns() // 1_000_000),
            )
            return user_id

    def issue_session(
        self,
        user_id: UserId,
        oidc_issuer: str,
        token_hash: bytes,
        csrf_hash: bytes,
        now_ms: int,
        expires_at_ms: int,
        max_active_sessions: int,
    ) -> tuple[str, AuthPrincipal]:
        _validate_window(now_ms, expires_at_ms)
        if max_active_sessions < 1:
            raise ValueError("每用户最大活跃会话数必须大于零")
        session_id = secrets.token_hex(16)
        with self._write() as connection:
            self._enforce_session_limit(
                connection, user_id, now_ms, max_active_sessions
            )
            self._insert_session(
                connection,
                session_id,
                user_id,
                oidc_issuer,
                token_hash,
                csrf_hash,
                now_ms,
                expires_at_ms,
            )
        return session_id, _principal(
            user_id, session_id, now_ms, expires_at_ms, oidc_issuer
        )

    def authenticate(
        self, token_hash: bytes, csrf_hash: bytes | None, now_ms: int
    ) -> AuthPrincipal:
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM auth_sessions WHERE token_hash=?", (token_hash,)
            ).fetchone()
        principal = _active_principal(row, now_ms)
        if csrf_hash is not None and not secrets.compare_digest(row["csrf_hash"], csrf_hash):
            raise CsrfValidationError("CSRF 令牌与当前会话不匹配")
        return principal

    def revoke(self, token_hash: bytes, now_ms: int) -> None:
        with self._write() as connection:
            cursor = connection.execute(
                """
                UPDATE auth_sessions SET revoked_at_ms=?
                WHERE token_hash=? AND revoked_at_ms IS NULL
                """,
                (now_ms, token_hash),
            )
            if cursor.rowcount != 1:
                raise AuthenticationError("会话无效或已撤销")

    def cleanup_expired(self, now_ms: int) -> int:
        with self._write() as connection:
            cursor = connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at_ms<=?", (now_ms,)
            )
        return cursor.rowcount

    def rotate_session(
        self,
        old_token_hash: bytes,
        new_token_hash: bytes,
        new_csrf_hash: bytes,
        now_ms: int,
        expires_at_ms: int,
    ) -> tuple[str, AuthPrincipal]:
        _validate_window(now_ms, expires_at_ms)
        new_session_id = secrets.token_hex(16)
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM auth_sessions WHERE token_hash=?", (old_token_hash,)
            ).fetchone()
            current = _active_principal(row, now_ms)
            self._insert_session(
                connection,
                new_session_id,
                current.user_id,
                current.oidc_issuer,
                new_token_hash,
                new_csrf_hash,
                now_ms,
                expires_at_ms,
            )
            cursor = connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at_ms=?, replaced_by_session_id=?
                WHERE session_id=? AND revoked_at_ms IS NULL
                """,
                (now_ms, new_session_id, current.session_id),
            )
            if cursor.rowcount != 1:
                raise AuthenticationError("会话已被并发轮换")
        return new_session_id, _principal(
            current.user_id,
            new_session_id,
            now_ms,
            expires_at_ms,
            current.oidc_issuer,
        )

    @staticmethod
    def _enforce_session_limit(
        connection: sqlite3.Connection,
        user_id: UserId,
        now_ms: int,
        max_active_sessions: int,
    ) -> None:
        connection.execute(
            """
            UPDATE auth_sessions SET revoked_at_ms=?
            WHERE user_id=? AND revoked_at_ms IS NULL AND expires_at_ms<=?
            """,
            (now_ms, user_id.value, now_ms),
        )
        rows = connection.execute(
            """
            SELECT session_id FROM auth_sessions
            WHERE user_id=? AND revoked_at_ms IS NULL
            ORDER BY authenticated_at_ms, session_id
            """,
            (user_id.value,),
        ).fetchall()
        remove_count = max(0, len(rows) - max_active_sessions + 1)
        if remove_count:
            connection.executemany(
                "UPDATE auth_sessions SET revoked_at_ms=? WHERE session_id=?",
                ((now_ms, row["session_id"]) for row in rows[:remove_count]),
            )

    @staticmethod
    def _insert_session(
        connection: sqlite3.Connection,
        session_id: str,
        user_id: UserId,
        oidc_issuer: str,
        token_hash: bytes,
        csrf_hash: bytes,
        now_ms: int,
        expires_at_ms: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO auth_sessions(
                session_id, user_id, oidc_issuer, token_hash, csrf_hash,
                authenticated_at_ms, expires_at_ms
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id.value,
                oidc_issuer,
                token_hash,
                csrf_hash,
                now_ms,
                expires_at_ms,
            ),
        )

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            yield connection

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._connection(immediate=True) as connection:
            yield connection

    @contextmanager
    def _connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.database_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _active_principal(row: sqlite3.Row | None, now_ms: int) -> AuthPrincipal:
    if row is None or row["revoked_at_ms"] is not None:
        raise AuthenticationError("会话无效或已撤销")
    if int(row["expires_at_ms"]) <= now_ms:
        raise AuthenticationError("会话已过期")
    return _principal(
        UserId.parse(row["user_id"]),
        str(row["session_id"]),
        int(row["authenticated_at_ms"]),
        int(row["expires_at_ms"]),
        str(row["oidc_issuer"]),
    )


def _principal(
    user_id: UserId,
    session_id: str,
    authenticated_at_ms: int,
    expires_at_ms: int,
    oidc_issuer: str,
) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id,
        session_id=session_id,
        authenticated_at_ms=authenticated_at_ms,
        expires_at_ms=expires_at_ms,
        oidc_issuer=oidc_issuer,
    )


def _validate_window(now_ms: int, expires_at_ms: int) -> None:
    if expires_at_ms <= now_ms:
        raise ValueError("会话过期时间必须晚于签发时间")
