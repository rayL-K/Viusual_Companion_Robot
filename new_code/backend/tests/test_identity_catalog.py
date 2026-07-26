from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from veyrasoul.identity import AnimaId, UserId
from veyrasoul.personalization import (
    ACTIVE,
    DELETED,
    DELETING,
    CatalogError,
    DataLayout,
    LifecycleConflictError,
    ObjectNotFoundError,
    RevisionConflictError,
    IdentityService,
    SqliteIdentityRepository,
)


def repository(tmp_path) -> SqliteIdentityRepository:
    layout = DataLayout(tmp_path / "data", tmp_path / "legacy.db")
    return SqliteIdentityRepository(layout.identity_database())


def service(tmp_path) -> IdentityService:
    layout = DataLayout(tmp_path / "data", tmp_path / "legacy.db")
    return IdentityService(
        SqliteIdentityRepository(layout.identity_database()), layout, "默认人设"
    )


def seed_two_users(repo: SqliteIdentityRepository) -> tuple[UserId, UserId, AnimaId]:
    alice = UserId.parse("alice")
    bob = UserId.parse("bob")
    rabbit = AnimaId.parse("rabbit")
    repo.create_user(alice, "Alice")
    repo.create_user(bob, "Bob")
    repo.create_anima(alice, rabbit, "月兔")
    return alice, bob, rabbit


def test_schema_migration_is_versioned_and_reopenable(tmp_path) -> None:
    repo = repository(tmp_path)
    repo.create_user(UserId.parse("alice"), "Alice")

    reopened = SqliteIdentityRepository(repo.database_path)
    assert reopened.get_user(UserId.parse("alice")).display_name == "Alice"
    with sqlite3.connect(repo.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"users", "animas"} <= tables


def test_unknown_future_schema_is_rejected(tmp_path) -> None:
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(CatalogError, match="高于程序支持"):
        SqliteIdentityRepository(path)


def test_user_and_multiple_anima_crud_is_owner_scoped(tmp_path) -> None:
    repo = repository(tmp_path)
    alice = UserId.parse("alice")
    repo.create_user(alice, " Alice   Chen ")
    rabbit = repo.create_anima(alice, AnimaId.parse("rabbit"), "月兔")
    fox = repo.create_anima(alice, AnimaId.parse("fox"), "小狐")

    assert repo.get_user(alice).display_name == "Alice Chen"
    assert repo.get_anima(alice, rabbit.id) == rabbit
    assert [item.id for item in repo.list_animas(alice)] == [rabbit.id, fox.id]

    renamed = repo.rename_anima(alice, rabbit.id, "月兔二号", rabbit.revision)
    assert renamed.display_name == "月兔二号"
    assert renamed.revision == 2
    assert repo.rename_user(alice, "Alice C.", 1).revision == 2


def test_active_io_lease_prevents_deletion_transition_until_release(tmp_path) -> None:
    identity = service(tmp_path)
    alice = UserId.parse("alice")
    rabbit = AnimaId.parse("rabbit")
    identity.create_user(alice, "Alice")
    identity.create_anima(alice, rabbit, "月兔")
    lease_entered = threading.Event()
    release_io = threading.Event()

    def active_io() -> None:
        with identity.active_anima_lease(alice, rabbit):
            lease_entered.set()
            assert release_io.wait(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        io_future = executor.submit(active_io)
        assert lease_entered.wait(2)
        deletion = executor.submit(
            identity.request_anima_deletion, alice, rabbit, 1
        )
        with pytest.raises(LifecycleConflictError, match="正在处理数据"):
            deletion.result(timeout=2)
        assert identity.get_anima(alice, rabbit).state == ACTIVE
        release_io.set()
        io_future.result(timeout=2)

    deleting = identity.request_anima_deletion(alice, rabbit, 1)
    assert deleting.state == DELETING


def test_finalize_rejects_unexpired_cross_process_lease(tmp_path) -> None:
    identity = service(tmp_path)
    alice = UserId.parse("alice")
    rabbit = AnimaId.parse("rabbit")
    identity.create_user(alice, "Alice")
    identity.create_anima(alice, rabbit, "月兔")
    deleting = identity.request_anima_deletion(alice, rabbit, 1)

    # Simulate a lease persisted by another process immediately before its
    # lifecycle observation. The finalizer must fail closed until it expires.
    now = int(time.time() * 1000)
    with sqlite3.connect(identity.repository.database_path) as connection:
        connection.execute(
            """
            INSERT INTO active_anima_leases(
                lease_id, owner_user_id, anima_id, expires_at_ms, created_at_ms
            ) VALUES(?, ?, ?, ?, ?)
            """,
            ("other-process", alice.value, rabbit.value, now + 60_000, now),
        )
    with pytest.raises(LifecycleConflictError, match="正在处理数据"):
        identity.finalize_anima_deletion(alice, rabbit, deleting.revision)
    assert identity.get_anima(alice, rabbit).state == DELETING


@pytest.mark.parametrize(
    "operation",
    [
        lambda repo, actor, anima: repo.get_anima(actor, anima),
        lambda repo, actor, anima: repo.rename_anima(actor, anima, "偷走", 1),
        lambda repo, actor, anima: repo.request_anima_deletion(actor, anima, 1),
        lambda repo, actor, anima: repo.finalize_anima_deletion(actor, anima, 1),
    ],
)
def test_cross_user_object_access_is_indistinguishable_from_missing(
    tmp_path, operation
) -> None:
    repo = repository(tmp_path)
    _alice, bob, rabbit = seed_two_users(repo)

    with pytest.raises(ObjectNotFoundError, match="Anima 不存在"):
        operation(repo, bob, rabbit)
    assert repo.get_anima(UserId.parse("alice"), rabbit).display_name == "月兔"


def test_list_never_leaks_another_users_animas(tmp_path) -> None:
    repo = repository(tmp_path)
    alice, bob, rabbit = seed_two_users(repo)
    repo.create_anima(bob, AnimaId.parse("fox"), "Bob 的小狐")

    assert [item.id for item in repo.list_animas(alice)] == [rabbit]
    assert [item.id for item in repo.list_animas(bob)] == [AnimaId.parse("fox")]


def test_stale_revision_cannot_overwrite_or_delete_newer_anima(tmp_path) -> None:
    repo = repository(tmp_path)
    alice, _bob, rabbit = seed_two_users(repo)
    saved = repo.rename_anima(alice, rabbit, "新名字", 1)

    with pytest.raises(RevisionConflictError):
        repo.rename_anima(alice, rabbit, "过期名字", 1)
    with pytest.raises(RevisionConflictError):
        repo.request_anima_deletion(alice, rabbit, 1)
    assert repo.get_anima(alice, rabbit) == saved


def test_parallel_updates_allow_exactly_one_revision_winner(tmp_path) -> None:
    repo = repository(tmp_path)
    alice, _bob, rabbit = seed_two_users(repo)

    def rename(name: str):
        try:
            return repo.rename_anima(alice, rabbit, name, 1)
        except RevisionConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(rename, ("并发甲", "并发乙")))

    winners = [result for result in results if not isinstance(result, Exception)]
    conflicts = [result for result in results if isinstance(result, RevisionConflictError)]
    assert len(winners) == len(conflicts) == 1
    assert repo.get_anima(alice, rabbit).revision == 2


def test_anima_two_phase_delete_can_cancel_or_finalize(tmp_path) -> None:
    repo = repository(tmp_path)
    alice, _bob, rabbit = seed_two_users(repo)

    deleting = repo.request_anima_deletion(alice, rabbit, 1)
    assert deleting.state == DELETING
    assert repo.get_anima(alice, rabbit).state == DELETING
    with pytest.raises(LifecycleConflictError):
        repo.rename_anima(alice, rabbit, "不允许", deleting.revision)

    restored = repo.cancel_anima_deletion(alice, rabbit, deleting.revision)
    assert restored.state == ACTIVE
    deleting_again = repo.request_anima_deletion(alice, rabbit, restored.revision)
    deleted = repo.finalize_anima_deletion(alice, rabbit, deleting_again.revision)
    assert deleted.state == DELETED
    with pytest.raises(ObjectNotFoundError):
        repo.get_anima(alice, rabbit)
    assert repo.list_animas(alice) == ()


def test_user_delete_cascades_lifecycle_without_cross_user_effects(tmp_path) -> None:
    repo = repository(tmp_path)
    alice, bob, rabbit = seed_two_users(repo)
    fox = repo.create_anima(bob, AnimaId.parse("fox"), "小狐")

    deleting = repo.request_user_deletion(alice, 1)
    assert deleting.state == DELETING
    assert repo.get_anima(alice, rabbit).state == DELETING
    assert repo.get_anima(bob, fox.id).state == ACTIVE
    with pytest.raises(ObjectNotFoundError):
        repo.create_anima(alice, AnimaId.parse("new-one"), "不允许")

    deleted = repo.finalize_user_deletion(alice, deleting.revision)
    assert deleted.state == DELETED
    with pytest.raises(ObjectNotFoundError):
        repo.get_user(alice)
    with pytest.raises(ObjectNotFoundError):
        repo.get_anima(alice, rabbit)
    assert repo.get_user(bob).state == ACTIVE


def test_same_public_anima_id_is_isolated_by_owner(tmp_path) -> None:
    repo = repository(tmp_path)
    alice, bob, rabbit = seed_two_users(repo)

    bob_rabbit = repo.create_anima(bob, rabbit, "Bob 的月兔")
    assert repo.get_anima(alice, rabbit).owner_id == alice
    assert repo.get_anima(bob, rabbit) == bob_rabbit


def test_service_authorizes_profile_access_and_removes_private_data(tmp_path) -> None:
    app = service(tmp_path)
    alice = UserId.parse("alice")
    bob = UserId.parse("bob")
    rabbit = AnimaId.parse("rabbit")
    app.create_user(alice, "Alice")
    app.create_user(bob, "Bob")
    anima = app.create_anima(alice, rabbit, "月兔")
    profile = app.profile_store(alice, rabbit)
    profile.update({"expectedRevision": 1, "personaMarkdown": "Alice 的私密人设"})

    with pytest.raises(ObjectNotFoundError):
        app.profile_store(bob, rabbit)
    deleting = app.request_anima_deletion(alice, rabbit, anima.revision)
    with pytest.raises(LifecycleConflictError):
        app.profile_store(alice, rabbit)
    private_directory = app.layout.anima_directory(alice, rabbit)
    assert private_directory.is_dir()

    app.finalize_anima_deletion(alice, rabbit, deleting.revision)
    assert not private_directory.exists()


def test_anima_cleanup_failure_stays_deleting_and_retry_succeeds(
    tmp_path, monkeypatch
) -> None:
    app = service(tmp_path)
    alice = UserId.parse("alice")
    rabbit = AnimaId.parse("rabbit")
    app.create_user(alice, "Alice")
    anima = app.create_anima(alice, rabbit, "月兔")
    app.profile_store(alice, rabbit).get()
    deleting = app.request_anima_deletion(alice, rabbit, anima.revision)
    private_directory = app.layout.anima_directory(alice, rabbit)
    real_rmtree = shutil.rmtree

    def fail_cleanup(_path) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(shutil, "rmtree", fail_cleanup)
    with pytest.raises(RuntimeError, match="simulated disk failure"):
        app.finalize_anima_deletion(alice, rabbit, deleting.revision)
    assert app.get_anima(alice, rabbit).state == DELETING
    assert private_directory.is_dir()

    monkeypatch.setattr(shutil, "rmtree", real_rmtree)
    assert app.finalize_anima_deletion(alice, rabbit, deleting.revision).state == DELETED
    assert not private_directory.exists()


def test_user_cleanup_failure_stays_deleting_and_retry_succeeds(
    tmp_path, monkeypatch
) -> None:
    app = service(tmp_path)
    alice = UserId.parse("alice")
    rabbit = AnimaId.parse("rabbit")
    app.create_user(alice, "Alice")
    app.create_anima(alice, rabbit, "月兔")
    app.profile_store(alice, rabbit).get()
    deleting = app.request_user_deletion(alice, 1)
    user_directory = app.layout.user_directory(alice)
    real_rmtree = shutil.rmtree

    def fail_cleanup(_path) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(shutil, "rmtree", fail_cleanup)
    with pytest.raises(RuntimeError, match="simulated disk failure"):
        app.finalize_user_deletion(alice, deleting.revision)
    assert app.get_user(alice).state == DELETING
    assert app.get_anima(alice, rabbit).state == DELETING
    assert user_directory.is_dir()

    monkeypatch.setattr(shutil, "rmtree", real_rmtree)
    assert app.finalize_user_deletion(alice, deleting.revision).state == DELETED
    assert not user_directory.exists()
