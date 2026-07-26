from __future__ import annotations

import pytest

from veyrasoul.providers import (
    Capability,
    Locality,
    ProviderConfigError,
    ProviderDescriptor,
    ProviderRegistry,
    default_provider_registry,
)


def test_default_registry_describes_current_local_and_cloud_adapters() -> None:
    registry = default_provider_registry()

    assert {
        (item.capability.value, item.name, item.locality.value)
        for item in registry.descriptors()
    } == {
        ("llm", "deepseek", "cloud"),
        ("llm", "disabled", "disabled"),
        ("asr", "sherpa", "local"),
        ("asr", "disabled", "disabled"),
        ("tts", "sherpa", "local"),
        ("tts", "disabled", "disabled"),
        ("vision", "local-vlm", "local"),
        ("vision", "disabled", "disabled"),
    }


def test_legacy_snapshot_preserves_existing_capabilities_shape() -> None:
    snapshot = default_provider_registry().parse_snapshot(
        {
            "llm": "deepseek",
            "asr": "sherpa",
            "tts": "sherpa",
            "vision": "local_vlm",
        }
    )

    assert snapshot.capabilities() == {
        "llm": "deepseek",
        "asr": "sherpa",
        "tts": "sherpa",
        "vision": "local-vlm",
    }
    assert snapshot.resolve("llm").locality is Locality.CLOUD
    assert snapshot.resolve(Capability.ASR).locality is Locality.LOCAL


def test_omitted_and_legacy_disabled_values_resolve_canonically() -> None:
    snapshot = default_provider_registry().parse_snapshot(
        {"llm": "deepseek", "asr": "off", "vision": None}
    )

    assert snapshot.capabilities() == {
        "llm": "deepseek",
        "asr": "disabled",
        "tts": "disabled",
        "vision": "disabled",
    }
    assert not snapshot.resolve("asr").enabled


def test_structured_snapshot_keeps_provider_config_immutable_and_serializable() -> None:
    source = {"model": "deepseek-chat", "options": {"temperature": 0.4}}
    snapshot = default_provider_registry().parse_snapshot(
        {
            "llm": {"provider": "deepseek", "locality": "cloud", "config": source},
            "asr": {"provider": "sherpa", "config": {"threads": 4}},
            "tts": {"provider": "sherpa"},
            "vision": {"provider": "local-vlm"},
        }
    )
    source["options"]["temperature"] = 1.0

    assert snapshot.resolve("llm").config["options"]["temperature"] == 0.4
    assert snapshot.as_dict()["llm"] == {
        "provider": "deepseek",
        "locality": "cloud",
        "config": {"model": "deepseek-chat", "options": {"temperature": 0.4}},
    }
    with pytest.raises(TypeError):
        snapshot.resolve("asr").config["threads"] = 8


def test_registration_validator_returns_canonical_config() -> None:
    registry = ProviderRegistry()
    for capability in Capability:
        registry.register_provider(capability, "disabled", Locality.DISABLED)

    def validate(config):
        threads = int(config.get("threads", 2))
        if not 1 <= threads <= 8:
            raise ValueError("threads must be between 1 and 8")
        return {"threads": threads}

    registry.register_provider("asr", "whisper", "local", validate_config=validate)
    snapshot = registry.parse_snapshot({"asr": {"provider": "whisper", "config": {"threads": "4"}}})

    assert snapshot.resolve("asr").config == {"threads": 4}


def test_registry_supports_multiple_localities_without_changing_capability_port() -> None:
    registry = default_provider_registry()
    registry.register_provider("vision", "cloud-vision", "cloud")

    local = registry.parse_snapshot({"vision": "local-vlm"})
    cloud = registry.parse_snapshot({"vision": "cloud-vision"})

    assert local.resolve("vision").capability is cloud.resolve("vision").capability
    assert local.resolve("vision").locality is Locality.LOCAL
    assert cloud.resolve("vision").locality is Locality.CLOUD


@pytest.mark.parametrize("capability", list(Capability))
def test_every_capability_supports_local_cloud_and_disabled_registration(capability) -> None:
    registry = ProviderRegistry()
    registry.register_provider(capability, "disabled", "disabled")
    registry.register_provider(capability, "on-device", "local")
    registry.register_provider(capability, "hosted", "cloud")

    assert registry.resolve(capability, "on-device").locality is Locality.LOCAL
    assert registry.resolve(capability, "hosted").locality is Locality.CLOUD
    assert registry.resolve(capability, None).locality is Locality.DISABLED


@pytest.mark.parametrize(
    ("snapshot", "message"),
    (
        ({"audio": "sherpa"}, "unsupported capabilities"),
        ({"llm": "missing"}, "not registered"),
        ({"llm": {"provider": "deepseek", "config": []}}, "config must be an object"),
        ({"llm": {"provider": "deepseek", "endpoint": "x"}}, "unsupported fields"),
        (
            {"llm": {"provider": "deepseek", "locality": "local"}},
            "registered as cloud",
        ),
    ),
)
def test_invalid_snapshot_fails_with_actionable_error(snapshot, message) -> None:
    with pytest.raises(ProviderConfigError, match=message):
        default_provider_registry().parse_snapshot(snapshot)


def test_duplicate_registration_is_rejected() -> None:
    registry = ProviderRegistry()
    descriptor = ProviderDescriptor("custom", Capability.LLM, Locality.LOCAL)
    registry.register(descriptor)

    with pytest.raises(ProviderConfigError, match="already registered"):
        registry.register(descriptor)


def test_disabled_provider_rejects_config_and_reserved_name_misuse() -> None:
    registry = default_provider_registry()

    with pytest.raises(ProviderConfigError, match="do not accept config"):
        registry.parse_snapshot({"tts": {"provider": "disabled", "config": {"voice": "x"}}})
    with pytest.raises(ProviderConfigError, match="reserved"):
        ProviderDescriptor("disabled", Capability.TTS, Locality.LOCAL)
    with pytest.raises(ProviderConfigError, match="unsupported locality"):
        ProviderDescriptor("custom", Capability.TTS, "edge")


def test_secret_config_is_not_exposed_by_repr() -> None:
    snapshot = default_provider_registry().parse_snapshot(
        {"llm": {"provider": "deepseek", "config": {"api_key": "secret-value"}}}
    )

    assert "secret-value" not in repr(snapshot)


def test_snapshot_serialization_recursively_redacts_sensitive_config() -> None:
    snapshot = default_provider_registry().parse_snapshot(
        {
            "llm": {
                "provider": "deepseek",
                "config": {
                    "api_key": "api-secret",
                    "model": "deepseek-chat",
                    "transport": {
                        "Authorization": "Bearer private",
                        "accessToken": "access-secret",
                        "timeout": 3,
                    },
                    "fallbacks": [
                        {"client_secret": "client-secret", "name": "backup"},
                        {"password": "password-secret"},
                    ],
                    "max_tokens": 256,
                },
            }
        }
    )

    serialized = snapshot.as_dict()["llm"]["config"]

    assert serialized == {
        "api_key": "[REDACTED]",
        "model": "deepseek-chat",
        "transport": {
            "Authorization": "[REDACTED]",
            "accessToken": "[REDACTED]",
            "timeout": 3,
        },
        "fallbacks": [
            {"client_secret": "[REDACTED]", "name": "backup"},
            {"password": "[REDACTED]"},
        ],
        "max_tokens": 256,
    }
    assert snapshot.resolve("llm").config["api_key"] == "api-secret"
    assert "api-secret" not in repr(snapshot.as_dict())
