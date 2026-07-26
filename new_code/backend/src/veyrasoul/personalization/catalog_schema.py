"""账号目录 SQLite schema 的单向迁移。"""

from __future__ import annotations

import sqlite3

from .catalog_model import CatalogError


SCHEMA_VERSION = 2


def migrate(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise CatalogError(f"目录数据库版本 {version} 高于程序支持的 {SCHEMA_VERSION}")
    if version == 0:
        _migration_1(connection)
        connection.execute("PRAGMA user_version=1")
        version = 1
    if version == 1:
        _migration_2(connection)
        connection.execute("PRAGMA user_version=2")


def _migration_1(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('active', 'deleting', 'deleted')),
            revision INTEGER NOT NULL CHECK(revision >= 1),
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );
        CREATE TABLE animas (
            anima_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL REFERENCES users(user_id),
            display_name TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('active', 'deleting', 'deleted')),
            revision INTEGER NOT NULL CHECK(revision >= 1),
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            PRIMARY KEY(owner_user_id, anima_id)
        );
        CREATE INDEX idx_animas_owner_state
        ON animas(owner_user_id, state, created_at_ms);
        """
    )


def _migration_2(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE active_anima_leases (
            lease_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            anima_id TEXT NOT NULL,
            expires_at_ms INTEGER NOT NULL,
            created_at_ms INTEGER NOT NULL,
            FOREIGN KEY(owner_user_id, anima_id)
                REFERENCES animas(owner_user_id, anima_id)
        );
        CREATE INDEX idx_active_anima_leases_target
        ON active_anima_leases(owner_user_id, anima_id, expires_at_ms);
        """
    )
