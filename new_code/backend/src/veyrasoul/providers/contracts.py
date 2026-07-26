"""Provider selection contracts shared by every multimodal capability.

The contracts deliberately describe *selection*, not provider implementation.
Adapters can keep their existing ports while the composition root chooses a
local or cloud implementation from a validated :class:`ProviderSnapshot`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping


REDACTED = "[REDACTED]"


class Capability(str, Enum):
    LLM = "llm"
    ASR = "asr"
    TTS = "tts"
    VISION = "vision"


class Locality(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"
    DISABLED = "disabled"


class ProviderConfigError(ValueError):
    """Raised when a provider selection snapshot is malformed."""


def normalize_name(value: object) -> str:
    """Normalize environment-style provider names without hiding bad input."""

    if not isinstance(value, str):
        raise ProviderConfigError("provider must be a string")
    normalized = value.strip().lower().replace("_", "-")
    if not normalized:
        raise ProviderConfigError("provider must not be empty")
    return normalized


def parse_capability(value: Capability | str) -> Capability:
    if isinstance(value, Capability):
        return value
    try:
        return Capability(str(value).strip().lower())
    except ValueError as exc:
        raise ProviderConfigError(f"unsupported capability: {value!r}") from exc


def parse_locality(value: Locality | str) -> Locality:
    if isinstance(value, Locality):
        return value
    try:
        return Locality(str(value).strip().lower())
    except ValueError as exc:
        raise ProviderConfigError(f"unsupported locality: {value!r}") from exc


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", str(key).lower())
    exact = {
        "apikey",
        "authorization",
        "bearertoken",
        "credential",
        "credentials",
        "password",
        "passwd",
        "passphrase",
        "privatekey",
        "secret",
        "token",
    }
    return normalized in exact or normalized.endswith(
        ("apikey", "credential", "password", "privatekey", "secret", "token")
    )


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _is_sensitive_key(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list, frozenset)):
        return [_redact(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Stable identity and placement metadata for one provider adapter."""

    name: str
    capability: Capability
    locality: Locality

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", normalize_name(self.name))
        object.__setattr__(self, "capability", parse_capability(self.capability))
        object.__setattr__(self, "locality", parse_locality(self.locality))
        if self.locality is Locality.DISABLED and self.name != "disabled":
            raise ProviderConfigError("disabled providers must use the canonical name 'disabled'")
        if self.name == "disabled" and self.locality is not Locality.DISABLED:
            raise ProviderConfigError("the provider name 'disabled' is reserved")


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """Resolved provider plus immutable, provider-owned configuration."""

    descriptor: ProviderDescriptor
    config: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.config, Mapping):
            raise ProviderConfigError("provider config must be an object")
        if self.descriptor.locality is Locality.DISABLED and self.config:
            raise ProviderConfigError("disabled providers do not accept config")
        object.__setattr__(self, "config", _freeze(self.config))

    @property
    def capability(self) -> Capability:
        return self.descriptor.capability

    @property
    def name(self) -> str:
        return self.descriptor.name

    @property
    def locality(self) -> Locality:
        return self.descriptor.locality

    @property
    def enabled(self) -> bool:
        return self.locality is not Locality.DISABLED

    def as_dict(self) -> dict[str, Any]:
        """Serialize public metadata while recursively removing credentials."""

        return {
            "provider": self.name,
            "locality": self.locality.value,
            "config": _redact(self.config),
        }


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    """One complete and internally consistent multimodal provider selection."""

    selections: Mapping[Capability, ProviderSelection]

    def __post_init__(self) -> None:
        normalized: dict[Capability, ProviderSelection] = {}
        for raw_capability, selection in self.selections.items():
            capability = parse_capability(raw_capability)
            if not isinstance(selection, ProviderSelection):
                raise ProviderConfigError(f"{capability.value} selection has an invalid type")
            if selection.capability is not capability:
                raise ProviderConfigError(
                    f"{capability.value} selection belongs to {selection.capability.value}"
                )
            normalized[capability] = selection
        missing = set(Capability) - set(normalized)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ProviderConfigError(f"snapshot is missing capabilities: {names}")
        object.__setattr__(self, "selections", MappingProxyType(normalized))

    def resolve(self, capability: Capability | str) -> ProviderSelection:
        return self.selections[parse_capability(capability)]

    def capabilities(self) -> dict[str, str]:
        """Return the existing health/API representation for port compatibility."""

        return {
            capability.value: self.selections[capability].name
            for capability in Capability
        }

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            capability.value: self.selections[capability].as_dict()
            for capability in Capability
        }
