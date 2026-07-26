"""Multimodal provider registry and configuration snapshot parser."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .contracts import (
    Capability,
    Locality,
    ProviderConfigError,
    ProviderDescriptor,
    ProviderSelection,
    ProviderSnapshot,
    normalize_name,
    parse_capability,
    parse_locality,
)

ConfigValidator = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]

_DISABLED_ALIASES = frozenset({"disabled", "none", "off", "false", "0"})


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    descriptor: ProviderDescriptor
    validate_config: ConfigValidator | None = None

    def selection(self, config: Mapping[str, Any] | None = None) -> ProviderSelection:
        values: Mapping[str, Any] = {} if config is None else config
        if not isinstance(values, Mapping):
            raise ProviderConfigError(
                f"{self.descriptor.capability.value}.{self.descriptor.name} config must be an object"
            )
        if self.validate_config is not None:
            try:
                validated = self.validate_config(values)
            except ProviderConfigError:
                raise
            except (TypeError, ValueError) as exc:
                raise ProviderConfigError(
                    f"invalid config for "
                    f"{self.descriptor.capability.value}.{self.descriptor.name}: {exc}"
                ) from exc
            values = {} if validated is None else validated
        return ProviderSelection(self.descriptor, values)


class ProviderRegistry:
    """Explicit registry; duplicate keys are rejected instead of overwritten."""

    def __init__(self) -> None:
        self._registrations: dict[tuple[Capability, str], ProviderRegistration] = {}

    def register(
        self,
        descriptor: ProviderDescriptor,
        *,
        validate_config: ConfigValidator | None = None,
    ) -> ProviderRegistration:
        registration = ProviderRegistration(descriptor, validate_config)
        key = (descriptor.capability, descriptor.name)
        if key in self._registrations:
            raise ProviderConfigError(
                f"provider already registered: {descriptor.capability.value}.{descriptor.name}"
            )
        self._registrations[key] = registration
        return registration

    def register_provider(
        self,
        capability: Capability | str,
        name: str,
        locality: Locality | str,
        *,
        validate_config: ConfigValidator | None = None,
    ) -> ProviderRegistration:
        return self.register(
            ProviderDescriptor(
                name=name,
                capability=parse_capability(capability),
                locality=parse_locality(locality),
            ),
            validate_config=validate_config,
        )

    def registration(
        self,
        capability: Capability | str,
        provider: str,
    ) -> ProviderRegistration:
        parsed_capability = parse_capability(capability)
        name = normalize_name(provider)
        if name in _DISABLED_ALIASES:
            name = "disabled"
        try:
            return self._registrations[(parsed_capability, name)]
        except KeyError as exc:
            raise ProviderConfigError(
                f"provider is not registered: {parsed_capability.value}.{name}"
            ) from exc

    def resolve(
        self,
        capability: Capability | str,
        provider: str | None,
        config: Mapping[str, Any] | None = None,
    ) -> ProviderSelection:
        name = "disabled" if provider is None else provider
        return self.registration(capability, name).selection(config)

    def parse_snapshot(self, value: Mapping[str, object]) -> ProviderSnapshot:
        """Parse legacy string values or structured provider selections.

        Legacy form remains valid::

            {"llm": "deepseek", "asr": "sherpa", ...}

        Structured form carries provider-owned settings without changing ports::

            {"llm": {"provider": "deepseek", "config": {"model": "chat"}}}
        """

        if not isinstance(value, Mapping):
            raise ProviderConfigError("provider snapshot must be an object")
        unknown = {str(key) for key in value} - {item.value for item in Capability}
        if unknown:
            raise ProviderConfigError(
                f"snapshot contains unsupported capabilities: {', '.join(sorted(unknown))}"
            )

        selections: dict[Capability, ProviderSelection] = {}
        for capability in Capability:
            raw = value.get(capability.value, "disabled")
            provider: str | None
            config: Mapping[str, Any] | None = None
            requested_locality: str | None = None
            if raw is None:
                provider = None
            elif isinstance(raw, str):
                provider = raw
            elif isinstance(raw, Mapping):
                extra = {str(key) for key in raw} - {"provider", "config", "locality"}
                if extra:
                    raise ProviderConfigError(
                        f"{capability.value} selection contains unsupported fields: "
                        f"{', '.join(sorted(extra))}"
                    )
                provider_value = raw.get("provider", "disabled")
                provider = None if provider_value is None else normalize_name(provider_value)
                config_value = raw.get("config", {})
                if not isinstance(config_value, Mapping):
                    raise ProviderConfigError(f"{capability.value} config must be an object")
                config = config_value
                locality_value = raw.get("locality")
                if locality_value is not None:
                    requested_locality = str(locality_value).strip().lower()
            else:
                raise ProviderConfigError(
                    f"{capability.value} selection must be a provider name or object"
                )

            selection = self.resolve(capability, provider, config)
            if requested_locality is not None and requested_locality != selection.locality.value:
                raise ProviderConfigError(
                    f"{capability.value}.{selection.name} is registered as "
                    f"{selection.locality.value}, not {requested_locality}"
                )
            selections[capability] = selection
        return ProviderSnapshot(selections)

    def descriptors(
        self,
        capability: Capability | str | None = None,
    ) -> tuple[ProviderDescriptor, ...]:
        selected = (
            self._registrations.values()
            if capability is None
            else (
                registration
                for (registered_capability, _), registration in self._registrations.items()
                if registered_capability is parse_capability(capability)
            )
        )
        return tuple(
            sorted(
                (registration.descriptor for registration in selected),
                key=lambda item: (item.capability.value, item.name),
            )
        )


def default_provider_registry() -> ProviderRegistry:
    """Registry matching the current production adapters and names."""

    registry = ProviderRegistry()
    for capability in Capability:
        registry.register_provider(capability, "disabled", Locality.DISABLED)
    registry.register_provider(Capability.LLM, "deepseek", Locality.CLOUD)
    registry.register_provider(Capability.ASR, "sherpa", Locality.LOCAL)
    registry.register_provider(Capability.TTS, "sherpa", Locality.LOCAL)
    registry.register_provider(Capability.VISION, "local-vlm", Locality.LOCAL)
    return registry
