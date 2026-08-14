from __future__ import annotations

import asyncio

import pytest

from veyrasoul.gateway.runtime import (
    AppServices,
    SessionCapacityError,
    SessionRegistry,
)
from veyrasoul.identity import AnimaId, SessionIdentity, UserId
from veyrasoul.providers import default_provider_registry


class _Llm:
    async def stream_reply(self, messages):
        del messages
        yield "unused"


class _Tts:
    async def synthesize(self, request):
        del request
        return b"RIFF", "audio/wav"


def _services(tmp_path, *, max_sessions: int) -> AppServices:
    snapshot = default_provider_registry().parse_snapshot(
        {
            "llm": "deepseek",
            "asr": "disabled",
            "tts": "sherpa",
            "vision": "disabled",
        }
    )
    return AppServices(
        memory_path=tmp_path / "legacy.db",
        data_root=tmp_path / "accounts",
        llm=_Llm(),
        tts=_Tts(),
        stable_system_prompt="stable",
        provider_snapshot=snapshot,
        max_sessions=max_sessions,
    )


def _identity(user: str) -> SessionIdentity:
    return SessionIdentity(
        UserId(user),
        AnimaId("anima"),
        anonymous=False,
        assurance="authenticated",
    )


def test_concurrent_acquires_share_one_session_kernel(tmp_path) -> None:
    async def scenario() -> None:
        registry = SessionRegistry(_services(tmp_path, max_sessions=1))
        first, second = await asyncio.gather(
            registry.acquire("same-session", _identity("alice")),
            registry.acquire("same-session", _identity("alice")),
        )

        assert first.runtime.kernel is second.runtime.kernel
        assert first.runtime.profiles is second.runtime.profiles

        await asyncio.gather(first.release(), second.release())

    asyncio.run(scenario())


def test_active_state_is_never_evicted_and_idle_state_is_lru_reusable(tmp_path) -> None:
    async def scenario() -> None:
        registry = SessionRegistry(_services(tmp_path, max_sessions=1))
        first = await registry.acquire("session-a", _identity("alice"))

        with pytest.raises(SessionCapacityError):
            await registry.acquire("session-b", _identity("bob"))

        # Capacity denial must not damage the active session or duplicate it.
        same = await registry.acquire("session-a", _identity("alice"))
        assert same.runtime.kernel is first.runtime.kernel
        await same.release()
        await first.release()

        # Once idle, A can be evicted and the slot can be used by B.
        second = await registry.acquire("session-b", _identity("bob"))
        assert second.runtime.identity.user_id == UserId("bob")
        await second.release()

    asyncio.run(scenario())


def test_failed_materialization_releases_capacity_reservation(tmp_path) -> None:
    async def scenario() -> None:
        registry = SessionRegistry(_services(tmp_path, max_sessions=1))
        original = registry._materialize

        async def fail_once(state, identity):
            del state, identity
            raise RuntimeError("materialization failed")

        registry._materialize = fail_once  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="materialization failed"):
            await registry.acquire("session-a", _identity("alice"))

        registry._materialize = original  # type: ignore[method-assign]
        lease = await registry.acquire("session-b", _identity("bob"))
        await lease.release()

    asyncio.run(scenario())
