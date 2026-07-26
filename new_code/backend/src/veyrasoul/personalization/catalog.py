"""维护 ToC 用户、Anima 归属和可审计删除状态的 SQLite 目录。"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from veyrasoul.identity import AnimaId, UserId


from .catalog_model import (
    ACTIVE,
    DELETED,
    DELETING,
    LIFECYCLE_STATES,
    Anima,
    CatalogError,
    LifecycleConflictError,
    ObjectNotFoundError,
    RevisionConflictError,
    User,
    display_name as validate_display_name,
    revision as validate_revision,
    row_to_anima,
    row_to_user,
)
from .catalog_schema import migrate


class SqliteIdentityRepository:
    """SQLite-backed authorization source; every Anima query is actor-scoped."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._migrate()

    def create_user(self, user_id: UserId, display_name: str) -> User:
        name = validate_display_name(display_name)
        now = _now_ms()
        try:
            with self._write() as connection:
                connection.execute(
                    """
                    INSERT INTO users(
                        user_id, display_name, state, revision, created_at_ms, updated_at_ms
                    ) VALUES(?, ?, 'active', 1, ?, ?)
                    """,
                    (user_id.value, name, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise CatalogError("user_id 已存在") from exc
        return User(user_id, name, ACTIVE, 1, now, now)

    def get_user(self, actor_id: UserId) -> User:
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE user_id=? AND state!='deleted'",
                (actor_id.value,),
            ).fetchone()
        if row is None:
            raise ObjectNotFoundError("用户不存在")
        return row_to_user(row)

    def rename_user(self, actor_id: UserId, display_name: str, expected_revision: int) -> User:
        return self._update_user(
            actor_id, validate_display_name(display_name), expected_revision
        )

    def create_anima(self, actor_id: UserId, anima_id: AnimaId, display_name: str) -> Anima:
        name = validate_display_name(display_name)
        now = _now_ms()
        try:
            with self._write() as connection:
                _require_active_user(connection, actor_id)
                connection.execute(
                    """
                    INSERT INTO animas(
                        anima_id, owner_user_id, display_name, state, revision,
                        created_at_ms, updated_at_ms
                    ) VALUES(?, ?, ?, 'active', 1, ?, ?)
                    """,
                    (anima_id.value, actor_id.value, name, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise CatalogError("anima_id 已存在") from exc
        return Anima(anima_id, actor_id, name, ACTIVE, 1, now, now)

    def get_anima(self, actor_id: UserId, anima_id: AnimaId) -> Anima:
        with self._read() as connection:
            row = _owned_anima(connection, actor_id, anima_id, include_deleted=False)
        if row is None:
            raise ObjectNotFoundError("Anima 不存在")
        return row_to_anima(row)

    def list_animas(self, actor_id: UserId) -> tuple[Anima, ...]:
        with self._read() as connection:
            _require_active_user(connection, actor_id)
            rows = connection.execute(
                """
                SELECT * FROM animas
                WHERE owner_user_id=? AND state!='deleted'
                ORDER BY created_at_ms, anima_id
                """,
                (actor_id.value,),
            ).fetchall()
        return tuple(row_to_anima(row) for row in rows)

    def rename_anima(
        self,
        actor_id: UserId,
        anima_id: AnimaId,
        display_name: str,
        expected_revision: int,
    ) -> Anima:
        return self._update_anima(
            actor_id,
            anima_id,
            expected_revision,
            display_name=validate_display_name(display_name),
        )

    def request_anima_deletion(
        self, actor_id: UserId, anima_id: AnimaId, expected_revision: int
    ) -> Anima:
        return self._update_anima(
            actor_id, anima_id, expected_revision, next_state=DELETING
        )

    def cancel_anima_deletion(
        self, actor_id: UserId, anima_id: AnimaId, expected_revision: int
    ) -> Anima:
        return self._update_anima(
            actor_id,
            anima_id,
            expected_revision,
            next_state=ACTIVE,
            required_state=DELETING,
        )

    def finalize_anima_deletion(
        self,
        actor_id: UserId,
        anima_id: AnimaId,
        expected_revision: int,
        *,
        before_finalize: Callable[[], None] | None = None,
    ) -> Anima:
        return self._update_anima(
            actor_id,
            anima_id,
            expected_revision,
            next_state=DELETED,
            required_state=DELETING,
            before_update=before_finalize,
        )

    def request_user_deletion(self, actor_id: UserId, expected_revision: int) -> User:
        now = _now_ms()
        with self._write() as connection:
            current = _require_user_revision(connection, actor_id, expected_revision)
            if current["state"] != ACTIVE:
                raise LifecycleConflictError("用户不处于 active 状态")
            connection.execute(
                """
                UPDATE users SET state='deleting', revision=revision+1, updated_at_ms=?
                WHERE user_id=? AND revision=?
                """,
                (now, actor_id.value, expected_revision),
            )
            connection.execute(
                """
                UPDATE animas SET state='deleting', revision=revision+1, updated_at_ms=?
                WHERE owner_user_id=? AND state='active'
                """,
                (now, actor_id.value),
            )
            row = connection.execute(
                "SELECT * FROM users WHERE user_id=?", (actor_id.value,)
            ).fetchone()
        return row_to_user(row)

    def finalize_user_deletion(
        self,
        actor_id: UserId,
        expected_revision: int,
        *,
        before_finalize: Callable[[], None] | None = None,
    ) -> User:
        now = _now_ms()
        with self._write() as connection:
            current = _require_user_revision(connection, actor_id, expected_revision)
            if current["state"] != DELETING:
                raise LifecycleConflictError("用户删除尚未进入 deleting 状态")
            if before_finalize is not None:
                before_finalize()
            connection.execute(
                """
                UPDATE animas SET state='deleted', revision=revision+1, updated_at_ms=?
                WHERE owner_user_id=? AND state!='deleted'
                """,
                (now, actor_id.value),
            )
            connection.execute(
                """
                UPDATE users SET state='deleted', revision=revision+1, updated_at_ms=?
                WHERE user_id=? AND revision=?
                """,
                (now, actor_id.value, expected_revision),
            )
            row = connection.execute(
                "SELECT * FROM users WHERE user_id=?", (actor_id.value,)
            ).fetchone()
        return row_to_user(row)

    def _update_user(
        self, actor_id: UserId, display_name: str, expected_revision: int
    ) -> User:
        now = _now_ms()
        with self._write() as connection:
            current = _require_user_revision(connection, actor_id, expected_revision)
            if current["state"] != ACTIVE:
                raise LifecycleConflictError("用户不处于 active 状态")
            connection.execute(
                """
                UPDATE users
                SET display_name=?, revision=revision+1, updated_at_ms=?
                WHERE user_id=? AND revision=?
                """,
                (display_name, now, actor_id.value, expected_revision),
            )
            row = connection.execute(
                "SELECT * FROM users WHERE user_id=?", (actor_id.value,)
            ).fetchone()
        return row_to_user(row)

    def _update_anima(
        self,
        actor_id: UserId,
        anima_id: AnimaId,
        expected_revision: int,
        *,
        display_name: str | None = None,
        next_state: str | None = None,
        required_state: str = ACTIVE,
        before_update: Callable[[], None] | None = None,
    ) -> Anima:
        now = _now_ms()
        with self._write() as connection:
            row = _owned_anima(connection, actor_id, anima_id, include_deleted=True)
            if row is None:
                raise ObjectNotFoundError("Anima 不存在")
            if int(row["revision"]) != validate_revision(expected_revision):
                raise RevisionConflictError("Anima 已被其他请求更新")
            if row["state"] != required_state:
                raise LifecycleConflictError(f"Anima 不处于 {required_state} 状态")
            name = display_name if display_name is not None else str(row["display_name"])
            state = next_state if next_state is not None else str(row["state"])
            if state not in LIFECYCLE_STATES:
                raise LifecycleConflictError("Anima 生命周期状态无效")
            if before_update is not None:
                before_update()
            connection.execute(
                """
                UPDATE animas
                SET display_name=?, state=?, revision=revision+1, updated_at_ms=?
                WHERE anima_id=? AND owner_user_id=? AND revision=?
                """,
                (name, state, now, anima_id.value, actor_id.value, expected_revision),
            )
            updated = _owned_anima(connection, actor_id, anima_id, include_deleted=True)
        return row_to_anima(updated)

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
        connection.execute("PRAGMA foreign_keys=ON")
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

    def _migrate(self) -> None:
        with self._lock, self._connection(immediate=True) as connection:
            migrate(connection)


def _require_active_user(connection: sqlite3.Connection, actor_id: UserId) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM users WHERE user_id=? AND state='active'", (actor_id.value,)
    ).fetchone()
    if row is None:
        raise ObjectNotFoundError("用户不存在")
    return row


def _require_user_revision(
    connection: sqlite3.Connection, actor_id: UserId, expected_revision: int
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM users WHERE user_id=? AND state!='deleted'", (actor_id.value,)
    ).fetchone()
    if row is None:
        raise ObjectNotFoundError("用户不存在")
    if int(row["revision"]) != validate_revision(expected_revision):
        raise RevisionConflictError("用户已被其他请求更新")
    return row


def _owned_anima(
    connection: sqlite3.Connection,
    actor_id: UserId,
    anima_id: AnimaId,
    *,
    include_deleted: bool,
) -> sqlite3.Row | None:
    state_clause = "" if include_deleted else "AND state!='deleted'"
    return connection.execute(
        f"""
        SELECT * FROM animas
        WHERE anima_id=? AND owner_user_id=? {state_clause}
        """,
        (anima_id.value, actor_id.value),
    ).fetchone()




def _now_ms() -> int:
    return int(time.time() * 1000)
