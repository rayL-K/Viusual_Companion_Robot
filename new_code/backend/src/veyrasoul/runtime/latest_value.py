"""Async latest-value slot for high-frequency perception streams."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class VersionedValue(Generic[T]):
    version: int
    value: T | None


class LatestValue(Generic[T]):
    """Keep only the newest value so stale perception cannot form a FIFO backlog."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._version = 0
        self._value: T | None = None

    async def publish(self, value: T) -> int:
        async with self._condition:
            self._version += 1
            self._value = value
            self._condition.notify_all()
            return self._version

    async def snapshot(self) -> VersionedValue[T]:
        async with self._condition:
            return VersionedValue(self._version, self._value)

    async def wait_for_update(self, after_version: int, timeout_seconds: float) -> VersionedValue[T]:
        async def wait() -> VersionedValue[T]:
            async with self._condition:
                await self._condition.wait_for(lambda: self._version > after_version)
                return VersionedValue(self._version, self._value)

        return await asyncio.wait_for(wait(), timeout=max(0.001, timeout_seconds))
