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
from .runtime import (
    AvailableProvider,
    ProviderFactory,
    ProviderResolutionError,
    ProviderResolver,
    ResolvedProviderSnapshot,
)

__all__ = [
    "AvailableProvider",
    "Capability",
    "Locality",
    "ProviderConfigError",
    "ProviderDescriptor",
    "ProviderFactory",
    "ProviderRegistration",
    "ProviderRegistry",
    "ProviderResolutionError",
    "ProviderResolver",
    "ProviderSelection",
    "ProviderSnapshot",
    "ResolvedProviderSnapshot",
    "default_provider_registry",
]
