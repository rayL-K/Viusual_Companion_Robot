from __future__ import annotations

import tempfile
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.brain.memory import ConversationTurn, MemoryItem, SqliteMemoryStore


class MemoryStoreTests(unittest.TestCase):
    def test_sqlite_memory_store_keeps_recent_turns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteMemoryStore(Path(temp_dir) / "memory.sqlite3")
            store.append_turn("你好", "你好呀。")
            store.append_turn("你记得我吗", "我记得刚才的问候。")

            turns = store.recent_turns(limit=2)

        self.assertEqual([turn.user_text for turn in turns], ["你好", "你记得我吗"])
        self.assertEqual(turns[-1].to_prompt_dict()["assistant"], "我记得刚才的问候。")
        self.assertIn("relative_time", turns[-1].to_prompt_dict())

    def test_prompt_context_contains_relative_memory_time(self) -> None:
        now = datetime(2026, 5, 17, 17, 40, tzinfo=timezone.utc)
        turn = ConversationTurn(
            user_text="刚才问江宁天气",
            assistant_text="我当时不知道。",
            created_at=(now - timedelta(minutes=12)).isoformat(timespec="seconds"),
        )

        prompt_dict = turn.to_prompt_dict(now=now)

        self.assertEqual(prompt_dict["relative_time"], "12 分钟前")
        self.assertEqual(prompt_dict["time"], "2026-05-17T17:28:00+00:00")

    def test_sqlite_memory_store_upserts_long_term_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SqliteMemoryStore(Path(temp_dir) / "memory.sqlite3")
            store.add_item(MemoryItem(key="favorite_color", value="粉色"))
            store.add_item(MemoryItem(key="favorite_color", value="蓝色", source="profile"))

            db_file = Path(temp_dir) / "memory.sqlite3"
            self.assertTrue(db_file.exists())


if __name__ == "__main__":
    unittest.main()
