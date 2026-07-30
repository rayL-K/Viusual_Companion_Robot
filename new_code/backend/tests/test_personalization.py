from __future__ import annotations

import sqlite3

import pytest

from veyrasoul.identity import AnimaId, InvalidIdentity, UserId, validate_session_hint
from veyrasoul.personalization import (
    DataLayout,
    ProfileConflictError,
    ProfileValidationError,
    SqliteAnimaProfileStore,
)
from veyrasoul.providers import Capability, Locality, ProviderRegistry


def test_identity_types_are_normalized_and_reject_path_input() -> None:
    assert UserId.parse("  Alice-01 ").value == "alice-01"
    assert AnimaId.parse("Rabbit_2").value == "rabbit_2"
    with pytest.raises(InvalidIdentity):
        UserId.parse("../../other-user")
    with pytest.raises(InvalidIdentity):
        AnimaId.parse("anima/name")
    assert validate_session_hint("anon_0123456789abcdef") == "anon_0123456789abcdef"
    with pytest.raises(InvalidIdentity):
        validate_session_hint("../same-session")


def test_layout_isolates_each_user_and_anima_below_data_root(tmp_path) -> None:
    root = tmp_path / "mutable-data"
    legacy = tmp_path / "legacy" / "memory.db"
    layout = DataLayout(root, legacy)
    alice = layout.state_database(UserId.parse("alice"), AnimaId.parse("rabbit"))
    bob = layout.state_database(UserId.parse("bob"), AnimaId.parse("rabbit"))
    other_anima = layout.state_database(UserId.parse("alice"), AnimaId.parse("fox"))

    assert len({alice, bob, other_anima}) == 3
    assert alice.name == bob.name == "state.sqlite3"
    assert alice.is_relative_to(root.resolve())
    assert bob.is_relative_to(root.resolve())
    anonymous = layout.state_database(UserId.anonymous_for("browser-session"), AnimaId.default())
    assert anonymous.is_relative_to(root.resolve())
    assert anonymous != legacy.resolve()


def test_profile_persists_to_sqlite_and_anima_markdown(tmp_path) -> None:
    layout = DataLayout(tmp_path / "data", tmp_path / "legacy.db")
    user = UserId.parse("alice")
    anima = AnimaId.parse("rabbit")
    store = SqliteAnimaProfileStore(layout, user, anima, "默认人设")

    initial = store.get()
    assert initial.persona_markdown == "默认人设"
    updated = store.update(
        {
            "expectedRevision": 1,
            "personaMarkdown": "# 月兔\n\n说话温柔但不造作。",
            "maxReplyChars": 88,
            "replyDelayMs": 120,
            "voiceId": "sid:3",
            "providers": {
                "asr": {"provider": "sherpa", "config": {"model": "zipformer-zh-en"}},
                "vision": {"provider": "local-vlm", "config": {"model": "qwen-vl"}},
                "llm": {"provider": "deepseek", "config": {"model": "deepseek-chat"}},
                "tts": {
                    "provider": "sherpa",
                    "config": {"model": "matcha", "voice": "warm.zh"},
                },
            },
        }
    )
    assert updated.revision == 2
    assert layout.persona_file(user, anima).read_text(encoding="utf-8") == (
        "# 月兔\n\n说话温柔但不造作。\n"
    )

    reopened = SqliteAnimaProfileStore(layout, user, anima, "另一个默认值")
    assert reopened.get() == updated
    assert reopened.get().provider_snapshot.resolve("tts").config == {
        "model": "matcha",
        "voice": "warm.zh",
    }
    with sqlite3.connect(layout.state_database(user, anima)) as connection:
        row = connection.execute(
            "SELECT max_reply_chars, reply_delay_ms, voice_id FROM anima_settings"
        ).fetchone()
    assert row == (88, 120, "sid:3")


@pytest.mark.parametrize("field", ["api_key", "base_url", "endpoint", "token"])
def test_profile_never_accepts_provider_credentials_or_endpoints(tmp_path, field) -> None:
    store = SqliteAnimaProfileStore(
        DataLayout(tmp_path / "data", tmp_path / "legacy.db"),
        UserId.parse("alice"),
        AnimaId.default(),
        "默认人设",
    )

    with pytest.raises(ProfileValidationError, match="server-managed"):
        store.update(
            {
                "expectedRevision": 1,
                "providers": {
                    "llm": {
                        "provider": "deepseek",
                        "config": {field: "must-not-be-stored"},
                    }
                },
            }
        )
    assert "must-not-be-stored" not in store.database_path.read_bytes().decode(
        "utf-8", errors="ignore"
    )


def test_profile_rejects_nested_secrets_even_with_a_permissive_custom_registry(tmp_path) -> None:
    registry = ProviderRegistry()
    for capability in Capability:
        registry.register_provider(capability, "disabled", Locality.DISABLED)
    registry.register_provider("llm", "custom", "cloud")
    store = SqliteAnimaProfileStore(
        DataLayout(tmp_path / "data", tmp_path / "legacy.db"),
        UserId.parse("alice"),
        AnimaId.default(),
        "默认人设",
        registry,
    )

    with pytest.raises(ProfileValidationError, match="server-managed"):
        store.update(
            {
                "expectedRevision": 1,
                "providers": {
                    "llm": {
                        "provider": "custom",
                        "config": {"transport": {"clientSecret": "must-not-persist"}},
                    }
                },
            }
        )


def test_profile_patch_is_strict_and_does_not_mutate_other_users(tmp_path) -> None:
    layout = DataLayout(tmp_path / "data", tmp_path / "legacy.db")
    alice = SqliteAnimaProfileStore(
        layout, UserId.parse("alice"), AnimaId.default(), "Alice 默认"
    )
    bob = SqliteAnimaProfileStore(
        layout, UserId.parse("bob"), AnimaId.default(), "Bob 默认"
    )
    alice.update({"expectedRevision": 1, "personaMarkdown": "Alice 私有人设", "maxReplyChars": 20})

    assert bob.get().persona_markdown == "Bob 默认"
    assert alice.database_path != bob.database_path
    with pytest.raises(ProfileValidationError):
        alice.update({"expectedRevision": 2, "maxReplyChars": 7})
    with pytest.raises(ProfileValidationError):
        alice.update({"expectedRevision": 2, "replyDelayMs": True})
    with pytest.raises(ProfileValidationError):
        alice.update({"expectedRevision": 2, "unexpected": "value"})


def test_existing_anima_markdown_is_imported_on_first_open(tmp_path) -> None:
    layout = DataLayout(tmp_path / "data", tmp_path / "legacy.db")
    user = UserId.parse("migrated-user")
    anima = AnimaId.default()
    persona = layout.persona_file(user, anima)
    persona.parent.mkdir(parents=True)
    persona.write_text("旧版 Anima.md 人设\n", encoding="utf-8")

    store = SqliteAnimaProfileStore(layout, user, anima, "新默认")
    assert store.get().persona_markdown == "旧版 Anima.md 人设"


def test_persona_mirror_failure_rolls_back_sqlite_update(tmp_path, monkeypatch) -> None:
    layout = DataLayout(tmp_path / "data", tmp_path / "legacy.db")
    user = UserId.parse("alice")
    anima = AnimaId.default()
    store = SqliteAnimaProfileStore(layout, user, anima, "原始人设")
    original = store.get()

    def fail_mirror(_persona: str) -> None:
        raise RuntimeError("simulated mirror failure")

    monkeypatch.setattr(store, "_write_persona_mirror", fail_mirror)
    with pytest.raises(RuntimeError, match="simulated mirror failure"):
        store.update({"expectedRevision": 1, "personaMarkdown": "不应提交的人设", "maxReplyChars": 99})

    restored = SqliteAnimaProfileStore(layout, user, anima, "另一个默认")
    assert restored.get() == original


def test_stale_profile_revision_cannot_overwrite_a_newer_editor(tmp_path) -> None:
    layout = DataLayout(tmp_path / "data", tmp_path / "legacy.db")
    user = UserId.parse("alice")
    anima = AnimaId.default()
    first = SqliteAnimaProfileStore(layout, user, anima, "原始人设")
    stale = SqliteAnimaProfileStore(layout, user, anima, "原始人设")
    assert first.get().revision == stale.get().revision == 1

    saved = first.update({"expectedRevision": 1, "personaMarkdown": "较新的编辑"})
    assert saved.revision == 2
    with pytest.raises(ProfileConflictError):
        stale.update({"expectedRevision": 1, "personaMarkdown": "过期编辑"})
    assert first.get().persona_markdown == "较新的编辑"
