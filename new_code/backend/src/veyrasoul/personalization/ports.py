"""Persistence port for replaceable local or remote Anima profile stores."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .model import AnimaProfile


class AnimaProfileRepository(Protocol):
    def get(self) -> AnimaProfile: ...

    def update(self, payload: Mapping[str, Any]) -> AnimaProfile: ...
