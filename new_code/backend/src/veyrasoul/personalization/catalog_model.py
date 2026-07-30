"""ToC 账号目录的领域对象、状态和边界错误。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from veyrasoul.identity import AnimaId, UserId


ACTIVE = "active"
DELETING = "deleting"
DELETED = "deleted"
LIFECYCLE_STATES = {ACTIVE, DELETING, DELETED}


class CatalogError(RuntimeError):
    """Base error for account and Anima catalog operations."""


class ObjectNotFoundError(CatalogError):
    """The object is absent or is not owned by the acting user."""


class RevisionConflictError(CatalogError):
    """An optimistic update was based on a stale object revision."""


class LifecycleConflictError(CatalogError):
    """The requested operation is invalid for the object's lifecycle state."""


class ResourceQuotaError(CatalogError):
    """A tenant-scoped durable resource limit would be exceeded."""


class ResourceBusyError(CatalogError):
    """The same resource is already being changed by another request."""


@dataclass(frozen=True, slots=True)
class ResourceQuotaConfig:
    max_animas_per_user: int = 8
    max_document_bytes: int = 2_000_000
    max_documents_per_anima: int = 100
    max_document_bytes_per_user: int = 100_000_000
    reservation_ttl_ms: int = 10 * 60 * 1000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_animas_per_user", self.max_animas_per_user),
            ("max_document_bytes", self.max_document_bytes),
            ("max_documents_per_anima", self.max_documents_per_anima),
            ("max_document_bytes_per_user", self.max_document_bytes_per_user),
            ("reservation_ttl_ms", self.reservation_ttl_ms),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} 必须是正整数")


@dataclass(frozen=True, slots=True)
class DocumentUsageReservation:
    owner_id: UserId
    anima_id: AnimaId
    document_id: str
    reservation_id: str


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    display_name: str
    state: str
    revision: int
    created_at_ms: int
    updated_at_ms: int


@dataclass(frozen=True, slots=True)
class Anima:
    id: AnimaId
    owner_id: UserId
    display_name: str
    state: str
    revision: int
    created_at_ms: int
    updated_at_ms: int


def row_to_user(row: sqlite3.Row | None) -> User:
    if row is None:
        raise CatalogError("用户更新后无法重新读取")
    return User(
        UserId.parse(row["user_id"]),
        str(row["display_name"]),
        str(row["state"]),
        int(row["revision"]),
        int(row["created_at_ms"]),
        int(row["updated_at_ms"]),
    )


def row_to_anima(row: sqlite3.Row | None) -> Anima:
    if row is None:
        raise CatalogError("Anima 更新后无法重新读取")
    return Anima(
        AnimaId.parse(row["anima_id"]),
        UserId.parse(row["owner_user_id"]),
        str(row["display_name"]),
        str(row["state"]),
        int(row["revision"]),
        int(row["created_at_ms"]),
        int(row["updated_at_ms"]),
    )


def display_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("display_name 必须是字符串")
    normalized = " ".join(value.strip().split())
    if not 1 <= len(normalized) <= 80 or "\x00" in normalized:
        raise ValueError("display_name 必须为 1-80 个有效字符")
    return normalized


def revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("expected_revision 必须是正整数")
    return value
