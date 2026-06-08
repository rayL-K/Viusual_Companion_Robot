"""机器人记忆模块。

当前先使用 SQLite 文件保存对话轮次和显式记忆项。这样本地开发、Firefly
板端运行和后续向量检索都可以共享同一个数据库入口。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional


@dataclass
class MemoryItem:
    """一条可被检索或摘要的长期记忆记录。"""

    key: str
    value: str
    source: str = "conversation"


@dataclass
class ConversationTurn:
    """一轮用户与机器人的对话。"""

    user_text: str
    assistant_text: str
    created_at: str

    def to_prompt_dict(self, now: Optional[datetime] = None) -> Dict[str, str]:
        """转换成可传给 LLM 的轻量上下文。"""

        reference_time = now or current_local_time()
        local_time = parse_memory_time(self.created_at).astimezone(reference_time.tzinfo)
        return {
            "time": local_time.isoformat(timespec="seconds"),
            "relative_time": describe_relative_time(local_time, reference_time),
            "user": self.user_text,
            "assistant": self.assistant_text,
        }


class SqliteMemoryStore:
    """基于 SQLite 文件的最小可用记忆仓库。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def append_turn(self, user_text: str, assistant_text: str) -> None:
        """保存一轮对话。"""

        with self._connection() as connection:
            connection.execute(
                "INSERT INTO conversation_turns(user_text, assistant_text, created_at) VALUES(?, ?, ?)",
                (user_text, assistant_text, current_local_time().isoformat(timespec="seconds")),
            )

    def recent_turns(self, limit: int = 6) -> List[ConversationTurn]:
        """读取最近几轮对话，按时间正序返回。"""

        safe_limit = max(1, min(int(limit), 20))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT user_text, assistant_text, created_at
                FROM conversation_turns
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            ConversationTurn(user_text=row[0], assistant_text=row[1], created_at=row[2])
            for row in reversed(rows)
        ]

    def add_item(self, item: MemoryItem) -> None:
        """保存或更新一条长期记忆。"""

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO memory_items(key, value, source)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (item.key, item.value, item.source),
            )

    def _connect(self) -> sqlite3.Connection:
        """建立 SQLite 连接，失败时给出包含路径的明确错误。"""

        try:
            return sqlite3.connect(str(self.db_path))
        except sqlite3.Error as exc:
            raise RuntimeError(f"SQLite 连接失败 [{self.db_path}]：{exc}") from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """连接上下文管理器，自动 commit 和 close。"""

        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        """初始化数据库表结构，仅在表不存在时创建。"""

        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_text TEXT NOT NULL,
                        assistant_text TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_items (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
        except sqlite3.Error as exc:
            raise RuntimeError(f"SQLite 建表失败 [{self.db_path}]：{exc}") from exc


def current_local_time() -> datetime:
    """返回带本地时区的当前时间，避免 LLM 把记忆误判到昨天或前天。"""

    return datetime.now().astimezone().replace(microsecond=0)


def parse_memory_time(value: str) -> datetime:
    """兼容新 ISO 时间和旧 SQLite CURRENT_TIMESTAMP 时间。"""

    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def describe_relative_time(past: datetime, now: datetime) -> str:
    """给 LLM 明确的相对时间，减少它凭聊天顺序猜“昨天”。"""

    delta_seconds = max(0, int((now - past.astimezone(now.tzinfo)).total_seconds()))
    if delta_seconds < 60:
        return "刚刚"
    if delta_seconds < 3600:
        return f"{delta_seconds // 60} 分钟前"
    if delta_seconds < 86400:
        return f"{delta_seconds // 3600} 小时前"
    days = delta_seconds // 86400
    if days == 1:
        return "昨天"
    return f"{days} 天前"
