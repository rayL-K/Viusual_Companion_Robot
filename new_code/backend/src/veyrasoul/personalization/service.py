"""组合归属授权、个性化存储和数据删除生命周期。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from veyrasoul.identity import AnimaId, UserId
from veyrasoul.providers import (
    ProviderRegistry,
    ProviderSnapshot,
    default_provider_registry,
)

from .catalog import (
    ACTIVE,
    Anima,
    DocumentUsageReservation,
    LifecycleConflictError,
    SqliteIdentityRepository,
    User,
)
from .layout import DataLayout
from .model import AnimaProfile
from .store import SqliteAnimaProfileStore


class IdentityService:
    """应用层入口；调用方不能绕过 actor-scoped 归属检查打开私有数据。"""

    def __init__(
        self,
        repository: SqliteIdentityRepository,
        layout: DataLayout,
        default_persona: str,
        provider_registry: ProviderRegistry | None = None,
        *,
        default_provider_snapshot: ProviderSnapshot | None = None,
        profile_validator: Callable[[AnimaProfile], None] | None = None,
    ) -> None:
        if repository.database_path != layout.identity_database():
            raise ValueError("目录数据库必须位于同一 DataLayout")
        self.repository = repository
        self.layout = layout
        self.default_persona = default_persona
        self.provider_registry = provider_registry or default_provider_registry()
        self.default_provider_snapshot = default_provider_snapshot
        self.profile_validator = profile_validator

    def create_user(self, user_id: UserId, display_name: str) -> User:
        return self.repository.create_user(user_id, display_name)

    def get_user(self, actor_id: UserId) -> User:
        return self.repository.get_user(actor_id)

    def rename_user(
        self, actor_id: UserId, display_name: str, expected_revision: int
    ) -> User:
        return self.repository.rename_user(actor_id, display_name, expected_revision)

    def create_anima(
        self, actor_id: UserId, anima_id: AnimaId, display_name: str
    ) -> Anima:
        return self.repository.create_anima(actor_id, anima_id, display_name)

    def get_anima(self, actor_id: UserId, anima_id: AnimaId) -> Anima:
        return self.repository.get_anima(actor_id, anima_id)

    def list_animas(self, actor_id: UserId) -> tuple[Anima, ...]:
        return self.repository.list_animas(actor_id)

    def rename_anima(
        self,
        actor_id: UserId,
        anima_id: AnimaId,
        display_name: str,
        expected_revision: int,
    ) -> Anima:
        return self.repository.rename_anima(
            actor_id, anima_id, display_name, expected_revision
        )

    def profile_store(
        self, actor_id: UserId, anima_id: AnimaId
    ) -> SqliteAnimaProfileStore:
        self.require_active_anima(actor_id, anima_id)
        return SqliteAnimaProfileStore(
            self.layout,
            actor_id,
            anima_id,
            self.default_persona,
            self.provider_registry,
            default_provider_snapshot=self.default_provider_snapshot,
            profile_validator=self.profile_validator,
        )

    def require_active_anima(self, actor_id: UserId, anima_id: AnimaId) -> Anima:
        """Authorize ownership and reject data access after deletion starts."""

        anima = self.repository.get_anima(actor_id, anima_id)
        if anima.state != ACTIVE:
            raise LifecycleConflictError("Anima 不处于 active 状态")
        return anima

    def active_anima_lease(
        self, actor_id: UserId, anima_id: AnimaId
    ) -> "ActiveAnimaLease":
        """Keep destructive lifecycle transitions behind a durable I/O lease."""

        return ActiveAnimaLease(
            repository=self.repository,
            actor_id=actor_id,
            anima_id=anima_id,
        )

    def reserve_document_usage(
        self,
        actor_id: UserId,
        anima_id: AnimaId,
        document_id: str,
        size_bytes: int,
    ) -> DocumentUsageReservation:
        return self.repository.reserve_document_usage(
            actor_id, anima_id, document_id, size_bytes
        )

    def commit_document_usage(
        self, reservation: DocumentUsageReservation
    ) -> None:
        self.repository.commit_document_usage(reservation)

    def rollback_document_usage(
        self, reservation: DocumentUsageReservation
    ) -> None:
        self.repository.rollback_document_usage(reservation)

    def release_document_usage(
        self, actor_id: UserId, anima_id: AnimaId, document_id: str
    ) -> None:
        self.repository.release_document_usage(actor_id, anima_id, document_id)

    def request_anima_deletion(
        self, actor_id: UserId, anima_id: AnimaId, expected_revision: int
    ) -> Anima:
        return self.repository.request_anima_deletion(
            actor_id, anima_id, expected_revision
        )


    def cancel_anima_deletion(
        self, actor_id: UserId, anima_id: AnimaId, expected_revision: int
    ) -> Anima:
        return self.repository.cancel_anima_deletion(
            actor_id, anima_id, expected_revision
        )

    def finalize_anima_deletion(
        self, actor_id: UserId, anima_id: AnimaId, expected_revision: int
    ) -> Anima:
        return self.repository.finalize_anima_deletion(
            actor_id,
            anima_id,
            expected_revision,
            before_finalize=lambda: self._remove_private_data(
                self.layout.anima_directory(actor_id, anima_id)
            ),
        )

    def request_user_deletion(
        self, actor_id: UserId, expected_revision: int
    ) -> User:
        return self.repository.request_user_deletion(actor_id, expected_revision)

    def finalize_user_deletion(
        self, actor_id: UserId, expected_revision: int
    ) -> User:
        return self.repository.finalize_user_deletion(
            actor_id,
            expected_revision,
            before_finalize=lambda: self._remove_private_data(
                self.layout.user_directory(actor_id)
            ),
        )

    def _remove_private_data(self, directory: Path) -> None:
        try:
            shutil.rmtree(directory)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise RuntimeError(f"无法清理用户私有数据 {directory}: {exc}") from exc


@dataclass(slots=True)
class ActiveAnimaLease:
    """Renewable cross-process guard used by long-lived realtime sessions."""

    repository: SqliteIdentityRepository
    actor_id: UserId
    anima_id: AnimaId
    ttl_ms: int = 300_000
    _lease_id: str = field(default="", repr=False)

    def __enter__(self) -> Anima:
        if self._lease_id:
            raise RuntimeError("Anima lease cannot be entered twice")
        anima, self._lease_id = self.repository.acquire_active_anima_lease(
            self.actor_id,
            self.anima_id,
            ttl_ms=self.ttl_ms,
        )
        return anima

    def renew(self) -> None:
        if not self._lease_id:
            raise LifecycleConflictError("Anima 活跃租约尚未建立")
        self.repository.renew_active_anima_lease(
            self.actor_id,
            self.anima_id,
            self._lease_id,
            ttl_ms=self.ttl_ms,
        )

    def __exit__(self, *_: object) -> None:
        lease_id, self._lease_id = self._lease_id, ""
        if lease_id:
            self.repository.release_active_anima_lease(
                self.actor_id,
                self.anima_id,
                lease_id,
            )
