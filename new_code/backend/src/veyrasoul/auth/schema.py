"""认证 SQLite schema 仅保存外部身份映射和凭据摘要。"""

from __future__ import annotations

import sqlite3


SCHEMA_VERSION = 2


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_schema_versions (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM auth_schema_versions"
    ).fetchone()
    current = int(row[0])
    if current > SCHEMA_VERSION:
        raise RuntimeError("认证数据库版本高于当前程序支持范围")
    if current < 1:
        _migration_1(connection)
        connection.execute("INSERT INTO auth_schema_versions(version) VALUES(1)")
        current = 1
    if current < 2:
        _migration_2(connection)
        connection.execute("INSERT INTO auth_schema_versions(version) VALUES(2)")


def _migration_1(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE auth_identities (
            issuer TEXT NOT NULL,
            subject TEXT NOT NULL,
            user_id TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (issuer, subject),
            UNIQUE (user_id)
        );

        CREATE TABLE auth_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            oidc_issuer TEXT NOT NULL,
            token_hash BLOB NOT NULL UNIQUE,
            csrf_hash BLOB NOT NULL,
            authenticated_at_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL,
            revoked_at_ms INTEGER,
            replaced_by_session_id TEXT,
            FOREIGN KEY (replaced_by_session_id) REFERENCES auth_sessions(session_id)
        );

        CREATE INDEX auth_sessions_user_idx
            ON auth_sessions(user_id, expires_at_ms);
        """
    )


def _migration_2(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE auth_login_attempts (
            state_hash BLOB PRIMARY KEY,
            nonce_hash BLOB NOT NULL,
            nonce_ciphertext BLOB NOT NULL,
            verifier_ciphertext BLOB NOT NULL,
            created_at_ms INTEGER NOT NULL,
            expires_at_ms INTEGER NOT NULL,
            consumed_at_ms INTEGER
        );

        CREATE INDEX auth_login_attempts_expiry_idx
            ON auth_login_attempts(expires_at_ms);
        """
    )
