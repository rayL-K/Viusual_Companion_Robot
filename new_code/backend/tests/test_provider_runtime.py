from __future__ import annotations

import asyncio

import pytest

from veyrasoul.gateway.runtime import AppServices, SessionRegistry
from veyrasoul.identity import AnimaId, SessionIdentity, UserId
from veyrasoul.integrations.sherpa_asr import SherpaAsrConfig, SherpaStreamingAsr
from veyrasoul.personalization import ProfileValidationError
from veyrasoul.providers import (
    Capability,
    ProviderResolutionError,
    ProviderResolver,
    default_provider_registry,
)


class _Capabilities:
    tts_streaming = True
    asr_streaming = False


class _Adapter:
    capabilities = _Capabilities()

    def __init__(self) -> None:
        self.warmups = 0
        self.closes = 0

    async def warmup(self) -> None:
        self.warmups += 1

    async def aclose(self) -> None:
        self.closes += 1

    async def stream_reply(self, messages):
        del messages
        yield "ok"

    async def synthesize(self, request):
        del request
        return b"RIFF-test", "audio/wav"


class _FailingCloseAdapter(_Adapter):
    async def aclose(self) -> None:
        self.closes += 1
        raise RuntimeError("adapter close failed")


def _snapshot(*, llm_model: str = "fast", tts_voice: str = "alloy"):
    return default_provider_registry().parse_snapshot(
        {
            "llm": {
                "provider": "deepseek",
                "config": {"model": llm_model},
            },
            "asr": "disabled",
            "tts": {
                "provider": "openai-compatible",
                "config": {"model": "speech-1", "voice": tts_voice},
            },
            "vision": "disabled",
        }
    )


def test_resolver_exposes_only_bound_secret_free_allowlisted_catalog() -> None:
    registry = default_provider_registry()
    resolver = ProviderResolver(registry)
    llm = _Adapter()
    # Capability names are modality-specific; an unrelated attribute on an
    # adapter must never make the public LLM catalog claim audio streaming.
    llm.capabilities = type("OddCapabilities", (), {"asr_streaming": True})()
    tts = _Adapter()
    resolver.register_instance("llm", "deepseek", llm, models=("fast",))
    resolver.register_instance(
        "tts",
        "openai-compatible",
        tts,
        models=("speech-1",),
        voices=("default", "alloy"),
    )

    catalog = resolver.available_providers()

    assert tuple((item.capability.value, item.alias) for item in catalog) == (
        ("llm", "deepseek"),
        ("tts", "openai-compatible"),
    )
    assert catalog[0].streaming is False
    assert catalog[1].streaming is True
    assert catalog[1].as_dict() == {
        "capability": "tts",
        "alias": "openai-compatible",
        "locality": "cloud",
        "models": ["speech-1"],
        "voices": ["default", "alloy"],
        "streaming": True,
    }
    with pytest.raises(AttributeError):
        catalog[0].alias = "forged"  # type: ignore[misc]


def test_sherpa_asr_catalog_reports_its_actual_streaming_capability(tmp_path) -> None:
    resolver = ProviderResolver(default_provider_registry())
    resolver.register_instance(
        "asr",
        "sherpa",
        SherpaStreamingAsr(SherpaAsrConfig(tmp_path)),
        models=("zipformer",),
    )

    (catalog,) = resolver.available_providers()
    assert catalog.capability is Capability.ASR
    assert catalog.streaming is True


def test_resolver_fails_closed_for_unknown_model_voice_and_unbound_alias() -> None:
    registry = default_provider_registry()
    resolver = ProviderResolver(registry)
    resolver.register_instance("llm", "deepseek", _Adapter(), models=("fast",))
    resolver.register_instance(
        "tts",
        "openai-compatible",
        _Adapter(),
        models=("speech-1",),
        voices=("default", "alloy"),
    )

    assert resolver.supports(_snapshot(), voice_id="alloy")
    assert not resolver.supports(_snapshot(llm_model="premium-unapproved"))
    assert not resolver.supports(_snapshot(tts_voice="unapproved"))
    assert not resolver.supports(_snapshot(), voice_id="unapproved")

    unbound = registry.parse_snapshot(
        {
            "llm": "deepseek",
            "asr": "disabled",
            "tts": "sherpa",
            "vision": "disabled",
        }
    )
    with pytest.raises(ProviderResolutionError, match="not available"):
        resolver.validate_snapshot(unbound)


def test_resolver_caches_factories_and_closes_shared_resources_once() -> None:
    async def scenario() -> None:
        registry = default_provider_registry()
        resolver = ProviderResolver(registry)
        shared = _Adapter()
        creations = 0

        def factory(_selection):
            nonlocal creations
            creations += 1
            return shared

        resolver.register_factory("llm", "deepseek", factory, models=("fast",))
        resolver.register_instance(
            "tts",
            "openai-compatible",
            shared,
            models=("speech-1",),
            voices=("default", "alloy"),
        )

        first = await resolver.resolve(_snapshot(), voice_id="alloy")
        second = await resolver.resolve(_snapshot(), voice_id="alloy")
        assert first.llm is second.llm is shared
        assert first.tts is second.tts is shared
        assert creations == 1

        await resolver.warmup()
        assert shared.warmups == 1
        await resolver.aclose()
        await resolver.aclose()
        assert shared.closes == 1
        with pytest.raises(RuntimeError, match="closed"):
            await resolver.resolve(_snapshot())

    asyncio.run(scenario())


def test_resolver_shutdown_attempts_every_adapter_after_one_close_fails() -> None:
    async def scenario() -> None:
        resolver = ProviderResolver(default_provider_registry())
        healthy = _Adapter()
        failing = _FailingCloseAdapter()
        resolver.register_instance("llm", "deepseek", healthy, models=("fast",))
        resolver.register_instance(
            "tts",
            "openai-compatible",
            failing,
            models=("speech-1",),
            voices=("default",),
        )

        with pytest.raises(RuntimeError, match="adapter close failed"):
            await resolver.aclose()

        assert failing.closes == 1
        assert healthy.closes == 1

    asyncio.run(scenario())


def test_realtime_session_freezes_provider_view_until_next_connection(tmp_path) -> None:
    async def scenario() -> None:
        registry = default_provider_registry()
        resolver = ProviderResolver(registry)
        llm = _Adapter()
        local_tts = _Adapter()
        cloud_tts = _Adapter()
        resolver.register_instance("llm", "deepseek", llm, models=("fast",))
        resolver.register_instance(
            "tts",
            "sherpa",
            local_tts,
            models=("local-voice",),
            voices=("default", "sid:3"),
        )
        resolver.register_instance(
            "tts",
            "openai-compatible",
            cloud_tts,
            models=("speech-1",),
            voices=("default", "alloy"),
        )
        initial = registry.parse_snapshot(
            {
                "llm": {"provider": "deepseek", "config": {"model": "fast"}},
                "asr": "disabled",
                "tts": {"provider": "sherpa", "config": {"model": "local-voice"}},
                "vision": "disabled",
            }
        )
        services = AppServices(
            memory_path=tmp_path / "legacy.db",
            data_root=tmp_path / "accounts",
            llm=llm,
            tts=local_tts,
            stable_system_prompt="stable",
            provider_snapshot=initial,
            provider_resolver=resolver,
        )
        sessions = SessionRegistry(services)
        identity = SessionIdentity(
            UserId("alice"),
            AnimaId("anima-a"),
            anonymous=False,
            assurance="authenticated",
        )

        first_lease = await sessions.acquire("same-session", identity)
        first = first_lease.runtime
        assert first.turn_service.tts is local_tts
        assert first.provider_snapshot.resolve(Capability.TTS).name == "sherpa"

        first.profiles.update(
            {
                "expectedRevision": 1,
                "voiceId": "alloy",
                "providers": {
                    "llm": {
                        "provider": "deepseek",
                        "config": {"model": "fast"},
                    },
                    "asr": "disabled",
                    "tts": {
                        "provider": "openai-compatible",
                        "config": {"model": "speech-1", "voice": "alloy"},
                    },
                    "vision": "disabled",
                },
            }
        )

        # A live connection remains internally consistent after settings.update.
        assert first.turn_service.tts is local_tts
        assert first.profile_for_turn().voice_id == "default"
        assert first.profile_for_turn().provider_snapshot.resolve("tts").name == "sherpa"

        # A reconnect with the same logical session gets a newly frozen provider view.
        second_lease = await sessions.acquire("same-session", identity)
        second = second_lease.runtime
        assert second.turn_service.tts is cloud_tts
        assert second.provider_voice_id == "alloy"
        assert second.provider_snapshot.resolve("tts").name == "openai-compatible"

        with pytest.raises(ProfileValidationError, match="server-managed"):
            second.profiles.update(
                {
                    "expectedRevision": 2,
                    "providers": {
                        "llm": "deepseek",
                        "asr": "disabled",
                        "tts": {
                            "provider": "openai-compatible",
                            "config": {"base_url": "https://attacker.invalid"},
                        },
                        "vision": "disabled",
                    },
                }
            )
        await second_lease.release()
        await first_lease.release()
        await resolver.aclose()

    asyncio.run(scenario())


def test_removed_provider_recovers_to_server_default_before_session_ready(tmp_path) -> None:
    async def scenario() -> None:
        registry = default_provider_registry()
        llm = _Adapter()
        local_tts = _Adapter()
        cloud_tts = _Adapter()
        local = registry.parse_snapshot(
            {
                "llm": {"provider": "deepseek", "config": {"model": "fast"}},
                "asr": "disabled",
                "tts": {"provider": "sherpa", "config": {"model": "local-voice"}},
                "vision": "disabled",
            }
        )
        cloud = _snapshot()
        identity = SessionIdentity(
            UserId("alice"),
            AnimaId("anima-a"),
            anonymous=False,
            assurance="authenticated",
        )

        old_resolver = ProviderResolver(registry)
        old_resolver.register_instance("llm", "deepseek", llm, models=("fast",))
        old_resolver.register_instance(
            "tts",
            "sherpa",
            local_tts,
            models=("local-voice",),
            voices=("default",),
        )
        old_resolver.register_instance(
            "tts",
            "openai-compatible",
            cloud_tts,
            models=("speech-1",),
            voices=("default", "alloy"),
        )
        old_sessions = SessionRegistry(
            AppServices(
                memory_path=tmp_path / "legacy.db",
                data_root=tmp_path / "accounts",
                llm=llm,
                tts=local_tts,
                stable_system_prompt="stable",
                provider_snapshot=local,
                provider_resolver=old_resolver,
            )
        )
        old_lease = await old_sessions.acquire("old-connection", identity)
        old_runtime = old_lease.runtime
        old_runtime.profiles.update(
            {
                "expectedRevision": 1,
                "providers": cloud.as_dict(),
                "voiceId": "alloy",
            }
        )

        # Simulate a later deployment where the cloud TTS binding was removed.
        new_resolver = ProviderResolver(registry)
        new_resolver.register_instance("llm", "deepseek", llm, models=("fast",))
        new_resolver.register_instance(
            "tts",
            "sherpa",
            local_tts,
            models=("local-voice",),
            voices=("default",),
        )
        new_sessions = SessionRegistry(
            AppServices(
                memory_path=tmp_path / "legacy.db",
                data_root=tmp_path / "accounts",
                llm=llm,
                tts=local_tts,
                stable_system_prompt="stable",
                provider_snapshot=local,
                provider_resolver=new_resolver,
            )
        )
        recovered_lease = await new_sessions.acquire("new-connection", identity)
        recovered = recovered_lease.runtime

        assert recovered.turn_service.tts is local_tts
        assert recovered.provider_snapshot == local
        assert recovered.provider_voice_id == "default"
        persisted = recovered.profiles.get()
        assert persisted.provider_snapshot == local
        assert persisted.voice_id == "default"
        assert persisted.revision == 3

        await recovered_lease.release()
        await old_lease.release()
        await old_resolver.aclose()
        await new_resolver.aclose()

    asyncio.run(scenario())
