"""Persist one Anima profile beside its isolated memory database."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Iterator, Mapping

from veyrasoul.identity import AnimaId, UserId

from .layout import DataLayout
from .model import AnimaProfile, ProfileValidationError


class SqliteAnimaProfileStore:
    def __init__(
        self,
        layout: DataLayout,
        user_id: UserId,
        anima_id: AnimaId,
        default_persona: str,
    ) -> None:
        self.layout = layout
        self.user_id = user_id
        self.anima_id = anima_id
        self.database_path = layout.state_database(user_id, anima_id)
        self.persona_path = layout.persona_file(user_id, anima_id)
        self.default_profile = AnimaProfile(default_persona)
        self._lock = threading.RLock()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.persona_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get(self) -> AnimaProfile:
        try:
            with self._lock, self._connection() as connection:
                profile = self._get_or_create(connection)
        except sqlite3.Error as exc:
            raise RuntimeError(f"无法读取 Anima 设置数据库 {self.database_path}: {exc}") from exc
        self._write_persona_mirror(profile.persona_markdown)
        return profile

    def update(self, payload: Mapping[str, Any]) -> AnimaProfile:
        current: AnimaProfile | None = None
        try:
            with self._lock, self._connection(immediate=True) as connection:
                current = self._get_or_create(connection)
                updated = current.apply_patch(payload)
                # The human-readable Anima.md is part of the public settings contract,
                # not a best-effort afterthought. Write it before committing SQLite so
                # a filesystem failure rolls the database transaction back as well.
                self._write_persona_mirror(updated.persona_markdown)
                self._upsert(connection, updated)
        except Exception as exc:
            if current is not None:
                with suppress(RuntimeError):
                    self._write_persona_mirror(current.persona_markdown)
            if isinstance(exc, ProfileValidationError):
                raise
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"无法更新 Anima 设置数据库 {self.database_path}: {exc}") from exc
        return updated

    def _get_or_create(self, connection: sqlite3.Connection) -> AnimaProfile:
        row = connection.execute(
            """
            SELECT persona_markdown, max_reply_chars, reply_delay_ms, voice_id, revision
            FROM anima_settings WHERE anima_id=?
            """,
            (self.anima_id.value,),
        ).fetchone()
        if row is not None:
            return _row_to_profile(row)
        profile = self._initial_profile()
        self._upsert(connection, profile)
        return profile

    def _initial_profile(self) -> AnimaProfile:
        if self.persona_path.is_file():
            try:
                return AnimaProfile(self.persona_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                raise RuntimeError(f"无法导入 {self.persona_path}: {exc}") from exc
        return self.default_profile

    @contextmanager
    def _connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.database_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
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

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS anima_settings (
                    anima_id TEXT PRIMARY KEY,
                    persona_markdown TEXT NOT NULL,
                    max_reply_chars INTEGER NOT NULL,
                    reply_delay_ms INTEGER NOT NULL,
                    voice_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )
                """
            )

    def _upsert(self, connection: sqlite3.Connection, profile: AnimaProfile) -> None:
        connection.execute(
            """
            INSERT INTO anima_settings(
                anima_id, persona_markdown, max_reply_chars, reply_delay_ms,
                voice_id, revision, updated_at_ms
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(anima_id) DO UPDATE SET
                persona_markdown=excluded.persona_markdown,
                max_reply_chars=excluded.max_reply_chars,
                reply_delay_ms=excluded.reply_delay_ms,
                voice_id=excluded.voice_id,
                revision=excluded.revision,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                self.anima_id.value,
                profile.persona_markdown,
                profile.max_reply_chars,
                profile.reply_delay_ms,
                profile.voice_id,
                profile.revision,
                int(time.time() * 1000),
            ),
        )

    def _write_persona_mirror(self, persona: str) -> None:
        try:
            if self.persona_path.read_text(encoding="utf-8").rstrip("\n") == persona:
                return
        except (FileNotFoundError, OSError, UnicodeError):
            pass
        temporary = self.persona_path.with_name(
            f".{self.persona_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            temporary.write_text(persona + "\n", encoding="utf-8", newline="\n")
            os.replace(temporary, self.persona_path)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise RuntimeError(f"设置已写入 SQLite，但无法同步 {self.persona_path}: {exc}") from exc


def _row_to_profile(row: sqlite3.Row) -> AnimaProfile:
    return AnimaProfile(
        persona_markdown=str(row["persona_markdown"]),
        max_reply_chars=int(row["max_reply_chars"]),
        reply_delay_ms=int(row["reply_delay_ms"]),
        voice_id=str(row["voice_id"]),
        revision=int(row["revision"]),
    )
