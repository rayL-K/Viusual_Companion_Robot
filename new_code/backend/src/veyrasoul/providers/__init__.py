"""Provider selection contracts for interchangeable local/cloud adapters."""

from .contracts import (
    Capability,
    Locality,
    ProviderConfigError,
    ProviderDescriptor,
    ProviderSelection,
    ProviderSnapshot,
)
from .registry import ProviderRegistration, ProviderRegistry, default_provider_registry

__all__ = [
    "Capability",
    "Locality",
    "ProviderConfigError",
    "ProviderDescriptor",
    "ProviderRegistration",
    "ProviderRegistry",
    "ProviderSelection",
    "ProviderSnapshot",
    "default_provider_registry",
]
