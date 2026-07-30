"""可由 lifespan、systemd timer 或任务调度器调用的认证过期清理。"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Callable, Protocol


class ExpiredRecordStore(Protocol):
    def cleanup_expired(self, now_ms: int) -> int: ...


@dataclass(frozen=True, slots=True)
class AuthCleanupReport:
    expired_sessions: int
    expired_login_attempts: int

    @property
    def total(self) -> int:
        return self.expired_sessions + self.expired_login_attempts


class AuthExpiryMaintenance:
    def __init__(
        self,
        session_store: ExpiredRecordStore,
        login_attempt_store: ExpiredRecordStore,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._session_store = session_store
        self._login_attempt_store = login_attempt_store
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    def run_once(self) -> AuthCleanupReport:
        now_ms = self._clock_ms()
        sessions = self._session_store.cleanup_expired(now_ms)
        attempts = self._login_attempt_store.cleanup_expired(now_ms)
        return AuthCleanupReport(sessions, attempts)


class PeriodicAuthExpiryMaintenance:
    """Own one supervised cleanup task for the application lifespan."""

    def __init__(
        self,
        maintenance: AuthExpiryMaintenance,
        *,
        interval_seconds: float = 3_600,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._maintenance = maintenance
        self._interval_seconds = interval_seconds
        self._on_error = on_error
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("auth maintenance is already running")
        await self._run_once()
        self._task = asyncio.create_task(
            self._run(),
            name="anima-auth-expiry-maintenance",
        )

    async def aclose(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self._run_once()

    async def _run_once(self) -> None:
        try:
            await asyncio.to_thread(self._maintenance.run_once)
        except Exception as exc:
            if self._on_error is not None:
                self._on_error(exc)
