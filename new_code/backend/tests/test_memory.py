from __future__ import annotations

import time

from veyrasoul.memory.retrieval import HybridRetriever
from veyrasoul.memory.store import MemoryDraft, MemoryStore


def test_lexical_rag_finds_related_chinese_memory(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.add_entry(
        kind="episode",
        title="深夜聊天",
        body="用户戴着眼镜坐在书桌前，专注地讨论机器人视觉系统。",
        source="conversation",
        importance=0.8,
    )
    store.add_entry(
        kind="episode",
        title="早餐",
        body="用户早上吃了面包和牛奶。",
        source="conversation",
        importance=0.3,
    )
    result = HybridRetriever(store).retrieve("书桌前戴眼镜讨论视觉的人", limit=2)
    assert result
    assert "书桌" in result[0].entry.body


def test_fact_revision_keeps_history_but_only_one_active_value(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    first = store.upsert_fact(
        subject="用户", predicate="喜欢的饮料", value="咖啡", confidence=0.9, source="explicit"
    )
    second = store.upsert_fact(
        subject="用户", predicate="喜欢的饮料", value="乌龙茶", confidence=0.95, source="explicit"
    )
    assert second != first
    fact = store.active_fact("用户", "喜欢的饮料")
    assert fact is not None
    assert fact["value"] == "乌龙茶"
    results = HybridRetriever(store).retrieve("用户喜欢的饮料", limit=5)
    assert any("乌龙茶" in item.entry.body for item in results)
    assert all("咖啡" not in item.entry.body for item in results)


def test_vector_candidate_can_join_lexical_candidates(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.add_entry(
        kind="document",
        title="设备",
        body="RK3588 使用共享内存。",
        source="docs",
        embedding=[1.0, 0.0],
        observed_at_ms=int(time.time() * 1000),
    )
    store.add_entry(
        kind="document",
        title="天气",
        body="今天有阵雨。",
        source="docs",
        embedding=[0.0, 1.0],
    )
    retriever = HybridRetriever(store, embed=lambda _: [1.0, 0.0])
    result = retriever.retrieve("完全没有词法重合的查询", limit=1)
    assert result[0].entry.title == "设备"
    assert result[0].vector_rank == 1


def test_batch_ingest_is_searchable(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    ids = store.add_entries(
        [
            MemoryDraft("document", f"章节 {index}", f"多模态机器人知识条目 {index}", "manual")
            for index in range(50)
        ]
    )
    assert len(ids) == 50
    assert HybridRetriever(store).retrieve("机器人知识条目 42", limit=1)
