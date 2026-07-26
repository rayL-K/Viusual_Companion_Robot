"""Bind every memory database to exactly one user and one Anima."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from veyrasoul.identity import AnimaId, UserId

from .store import MemoryStore


class NamespaceMismatch(PermissionError):
    """Raised before data can cross a user/Anima boundary."""


@dataclass(frozen=True, slots=True)
class MemoryNamespace:
    user_id: UserId
    anima_id: AnimaId

    @classmethod
    def parse(cls, user_id: object, anima_id: object) -> "MemoryNamespace":
        return cls(UserId.parse(user_id), AnimaId.parse(anima_id))

    @property
    def key(self) -> str:
        return f"{self.user_id.value}/{self.anima_id.value}"


def bind_store(store: MemoryStore, namespace: MemoryNamespace) -> None:
    """Atomically claim an empty database or verify its existing owner."""

    with store.connection(immediate=True) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_namespace (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                user_id TEXT NOT NULL,
                anima_id TEXT NOT NULL
            )
            """
        )
        row = connection.execute(
            "SELECT user_id, anima_id FROM memory_namespace WHERE singleton=1"
        ).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO memory_namespace(singleton, user_id, anima_id)
                VALUES(1, ?, ?)
                """,
                (namespace.user_id.value, namespace.anima_id.value),
            )
            return
        if (
            str(row["user_id"]) != namespace.user_id.value
            or str(row["anima_id"]) != namespace.anima_id.value
        ):
            raise NamespaceMismatch(
                "memory database belongs to a different user/anima namespace"
            )


def assert_bound_store(store: MemoryStore, namespace: MemoryNamespace) -> None:
    try:
        bind_store(store, namespace)
    except sqlite3.DatabaseError as exc:
        raise NamespaceMismatch("memory namespace metadata is invalid") from exc
