"""Validated account and Anima identities used at every storage boundary."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol


_IDENTIFIER = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")
_SESSION_HINT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_:-]{0,98}[A-Za-z0-9])?$")


class InvalidIdentity(ValueError):
    """Raised when an untrusted identifier cannot be represented safely."""


@dataclass(frozen=True, slots=True)
class UserId:
    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, "user_id")

    @classmethod
    def parse(cls, value: object) -> "UserId":
        return cls(_normalize_identifier(value, "user_id"))

    @classmethod
    def anonymous(cls) -> "UserId":
        return cls("anonymous")

    @classmethod
    def anonymous_for(cls, session_id: str) -> "UserId":
        normalized = str(session_id or "").strip()
        if not normalized:
            raise InvalidIdentity("匿名身份需要稳定的 session_id")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
        return cls(f"anon_{digest}")


@dataclass(frozen=True, slots=True)
class AnimaId:
    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, "anima_id")

    @classmethod
    def parse(cls, value: object) -> "AnimaId":
        return cls(_normalize_identifier(value, "anima_id"))

    @classmethod
    def default(cls) -> "AnimaId":
        return cls("default")


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    user_id: UserId
    anima_id: AnimaId
    anonymous: bool
    assurance: str

    def __post_init__(self) -> None:
        if self.assurance not in {
            "anonymous_session_hint",
            "authenticated",
            "client_asserted",
        }:
            raise InvalidIdentity("identity assurance 类型无效")


class IdentityResolver(Protocol):
    def __call__(
        self,
        raw_user_id: object,
        raw_anima_id: object,
        session_id: str,
    ) -> SessionIdentity: ...


def storage_key(prefix: str, value: str) -> str:
    """Return a filesystem-safe, case-stable key without exposing the public id."""

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


def validate_session_hint(value: object) -> str:
    normalized = str(value or "").strip()
    if not _SESSION_HINT.fullmatch(normalized):
        raise InvalidIdentity(
            "session_id 仅允许 1-100 位字母、数字、下划线、连字符或冒号，且首尾必须为字母或数字"
        )
    return normalized


def _normalize_identifier(value: object, name: str) -> str:
    normalized = str(value or "").strip().lower()
    _validate_identifier(normalized, name)
    return normalized


def _validate_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise InvalidIdentity(
            f"{name} 仅允许 1-64 位小写字母、数字、下划线或连字符，且首尾必须为字母或数字"
        )
