from __future__ import annotations

from veyrasoul.memory import FactCandidate, HybridRetriever, MemoryCurator, MemoryStore


def test_repeated_preference_is_reinforced_without_duplicate_memory(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    curator = MemoryCurator(store)

    created = curator.curate(
        FactCandidate(
            subject=" 用户 ",
            predicate="喜欢的饮料",
            value="咖啡。",
            confidence=0.9,
            source="turn:1",
            evidence_kind="explicit",
            observed_at_ms=1_000,
        )
    )
    reinforced = curator.curate(
        FactCandidate(
            subject="用户",
            predicate="喜欢的饮料",
            value=" 咖啡 ",
            confidence=0.99,
            source="turn:2",
            evidence_kind="inference",
            observed_at_ms=2_000,
        )
    )

    assert created.fact_id == reinforced.fact_id
    assert reinforced.action == "reinforced"
    assert len(store.fact_history("用户", "喜欢的饮料")) == 1
    fact = store.active_fact("用户", "喜欢的饮料")
    assert fact is not None
    assert fact["confidence"] == 0.9
    evidence = store.fact_evidence(created.fact_id)
    assert [item["source"] for item in evidence] == ["turn:1", "turn:2"]
    matches = HybridRetriever(store).retrieve("用户喜欢什么饮料", limit=5)
    assert len([item for item in matches if item.entry.kind == "fact"]) == 1
    assert matches[0].entry.metadata is not None
    assert matches[0].entry.metadata["sources"] == ["turn:1", "turn:2"]
    assert matches[0].entry.importance == 0.85


def test_weak_visual_contradiction_is_kept_as_evidence_not_active_fact(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    curator = MemoryCurator(store)
    original = curator.curate(
        FactCandidate(
            "用户",
            "喜欢的饮料",
            "咖啡",
            0.9,
            "turn:1",
            evidence_kind="explicit",
        )
    )

    conflict = curator.curate(
        FactCandidate(
            "用户",
            "喜欢的饮料",
            "乌龙茶",
            0.99,
            "camera:42",
            evidence_kind="vision",
        )
    )

    assert conflict.fact_id == original.fact_id
    assert conflict.action == "conflict_ignored"
    assert store.active_fact("用户", "喜欢的饮料")["value"] == "咖啡"  # type: ignore[index]
    assert len(store.fact_history("用户", "喜欢的饮料")) == 1
    evidence = store.fact_evidence(original.fact_id)
    assert evidence[-1]["claimed_value"] == "乌龙茶"
    assert evidence[-1]["decision"] == "conflict_ignored"


def test_strong_explicit_correction_creates_traceable_revision(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    curator = MemoryCurator(store)
    first = curator.curate(
        FactCandidate(
            "用户",
            "喜欢的饮料",
            "咖啡",
            0.95,
            "camera:1",
            evidence_kind="vision",
            observed_at_ms=1_000,
        )
    )
    corrected = curator.curate(
        FactCandidate(
            "用户",
            "喜欢的饮料",
            "乌龙茶",
            0.8,
            "turn:7",
            evidence_kind="explicit",
            observed_at_ms=2_000,
        )
    )

    assert corrected.action == "revised"
    assert corrected.fact_id != first.fact_id
    history = store.fact_history("用户", "喜欢的饮料")
    assert [item["value"] for item in history] == ["咖啡", "乌龙茶"]
    assert history[0]["active"] == 0
    assert history[1]["supersedes_fact_id"] == history[0]["id"]
    assert store.fact_evidence(corrected.fact_id)[0]["decision"] == "revised"

    matches = HybridRetriever(store).retrieve("用户喜欢的饮料", limit=5)
    assert any("乌龙茶" in item.entry.body for item in matches)
    assert all("咖啡" not in item.entry.body for item in matches)


def test_many_repeated_observations_keep_one_active_memory(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    curator = MemoryCurator(store)
    results = curator.curate_many(
        FactCandidate(
            "用户",
            "希望的称呼",
            "主人",
            0.8,
            f"turn:{index}",
            evidence_kind="conversation",
            observed_at_ms=index + 1,
        )
        for index in range(200)
    )

    assert len(results) == 200
    assert results[0].action == "created"
    assert all(result.fact_id == results[0].fact_id for result in results)
    assert len(store.fact_history("用户", "希望的称呼")) == 1
    assert len(store.fact_evidence(results[0].fact_id)) == 200
