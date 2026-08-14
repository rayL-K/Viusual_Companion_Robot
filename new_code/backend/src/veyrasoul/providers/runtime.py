"""Server-owned runtime bindings for validated multimodal provider snapshots.

The public :mod:`veyrasoul.providers.registry` describes which selection
shapes are syntactically valid.  This module is the stricter production
boundary: only adapters actually bound by the composition root are available,
and model/voice identifiers must come from server-owned allowlists.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from veyrasoul.orchestration.ports import (
    SpeechSynthesizer,
    StreamingAsrFactory,
    StreamingLlm,
)
from veyrasoul.perception import VisionAnalyzer

from .contracts import (
    Capability,
    Locality,
    ProviderConfigError,
    ProviderSelection,
    ProviderSnapshot,
    parse_capability,
)
from .registry import ProviderRegistry


class ProviderResolutionError(ProviderConfigError):
    """A valid public selection is not available in this server process."""


@dataclass(frozen=True, slots=True)
class AvailableProvider:
    """Immutable, secret-free catalog entry exposed to clients."""

    capability: Capability
    alias: str
    locality: Locality
    models: tuple[str, ...] = ()
    voices: tuple[str, ...] = ()
    streaming: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "capability": self.capability.value,
            "alias": self.alias,
            "locality": self.locality.value,
            "models": list(self.models),
            "voices": list(self.voices),
            "streaming": self.streaming,
        }


ProviderFactory = Callable[[ProviderSelection], object]


@dataclass(frozen=True, slots=True)
class _RuntimeBinding:
    catalog: AvailableProvider
    factory: ProviderFactory


@dataclass(frozen=True, slots=True)
class ResolvedProviderSnapshot:
    """Connection-scoped immutable view over application-owned adapters."""

    snapshot: ProviderSnapshot
    llm: StreamingLlm
    tts: SpeechSynthesizer
    asr: StreamingAsrFactory | None
    vision: VisionAnalyzer | None
    voice_id: str


class ProviderResolver:
    """Resolve validated snapshots to bounded, application-owned adapters.

    Factories are called at most once for every allowlisted public selection.
    Consequently HTTP clients and native engines retain their connection/model
    pools across realtime sessions.  ``aclose`` owns every constructed adapter
    and deduplicates aliases that intentionally share one instance.
    """

    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry
        self._bindings: dict[tuple[Capability, str], _RuntimeBinding] = {}
        self._instances: dict[tuple[Capability, str, tuple[tuple[str, str], ...]], object] = {}
        self._owned_instances: list[object] = []
        self._lock = asyncio.Lock()
        self._closed = False

    def register_factory(
        self,
        capability: Capability | str,
        alias: str,
        factory: ProviderFactory,
        *,
        models: tuple[str, ...] = (),
        voices: tuple[str, ...] = (),
        streaming: bool = False,
    ) -> AvailableProvider:
        parsed = parse_capability(capability)
        registration = self.registry.registration(parsed, alias)
        descriptor = registration.descriptor
        if descriptor.locality is Locality.DISABLED:
            raise ProviderResolutionError("disabled is implicit and cannot have a runtime factory")
        key = (parsed, descriptor.name)
        if key in self._bindings:
            raise ProviderResolutionError(
                f"runtime provider already bound: {parsed.value}.{descriptor.name}"
            )
        if not callable(factory):
            raise TypeError("provider factory must be callable")
        catalog = AvailableProvider(
            capability=parsed,
            alias=descriptor.name,
            locality=descriptor.locality,
            models=_public_values(models, "model"),
            voices=_public_values(voices, "voice"),
            streaming=bool(streaming),
        )
        self._bindings[key] = _RuntimeBinding(catalog, factory)
        return catalog

    def register_instance(
        self,
        capability: Capability | str,
        alias: str,
        instance: object,
        *,
        models: tuple[str, ...] = (),
        voices: tuple[str, ...] = (),
    ) -> AvailableProvider:
        if instance is None:
            raise TypeError("provider instance must not be None")
        parsed = parse_capability(capability)
        capabilities = getattr(instance, "capabilities", None)
        streaming_attribute = {
            Capability.TTS: "tts_streaming",
            Capability.ASR: "asr_streaming",
        }.get(parsed)
        streaming = bool(
            streaming_attribute
            and getattr(capabilities, streaming_attribute, False)
        )
        catalog = self.register_factory(
            capability,
            alias,
            lambda _selection: instance,
            models=models,
            voices=voices,
            streaming=streaming,
        )
        self._owned_instances.append(instance)
        return catalog

    def available_providers(self) -> tuple[AvailableProvider, ...]:
        return tuple(
            binding.catalog
            for _, binding in sorted(
                self._bindings.items(),
                key=lambda item: (item[0][0].value, item[0][1]),
            )
        )

    def validate_snapshot(
        self,
        snapshot: ProviderSnapshot,
        *,
        voice_id: str = "default",
    ) -> ProviderSnapshot:
        """Canonicalize through the registry, then enforce runtime availability."""

        if not isinstance(snapshot, ProviderSnapshot):
            raise ProviderResolutionError("providers must be a ProviderSnapshot")
        canonical: dict[Capability, ProviderSelection] = {}
        for capability in Capability:
            requested = snapshot.resolve(capability)
            selection = self.registry.resolve(
                capability,
                requested.name,
                requested.config,
            )
            if selection.locality is Locality.DISABLED:
                canonical[capability] = selection
                continue
            binding = self._bindings.get((capability, selection.name))
            if binding is None:
                raise ProviderResolutionError(
                    f"provider is not available on this server: "
                    f"{capability.value}.{selection.name}"
                )
            _validate_public_config(selection, binding.catalog)
            canonical[capability] = selection

        resolved = ProviderSnapshot(canonical)
        if not resolved.resolve(Capability.LLM).enabled:
            raise ProviderResolutionError("llm provider cannot be disabled")
        if not resolved.resolve(Capability.TTS).enabled:
            raise ProviderResolutionError("tts provider cannot be disabled")
        _validate_runtime_voice(resolved, voice_id, self._bindings)
        return resolved

    def supports(
        self,
        snapshot: ProviderSnapshot,
        *,
        voice_id: str = "default",
    ) -> bool:
        try:
            self.validate_snapshot(snapshot, voice_id=voice_id)
        except (ProviderConfigError, TypeError, ValueError):
            return False
        return True

    async def resolve(
        self,
        snapshot: ProviderSnapshot,
        *,
        voice_id: str = "default",
    ) -> ResolvedProviderSnapshot:
        canonical = self.validate_snapshot(snapshot, voice_id=voice_id)
        async with self._lock:
            if self._closed:
                raise RuntimeError("provider resolver is closed")
            values: dict[Capability, object | None] = {}
            for capability in Capability:
                selection = canonical.resolve(capability)
                if not selection.enabled:
                    values[capability] = None
                    continue
                key = _instance_key(selection)
                instance = self._instances.get(key)
                if instance is None:
                    binding = self._bindings[(capability, selection.name)]
                    instance = binding.factory(selection)
                    if inspect.isawaitable(instance):
                        raise TypeError("provider factories must be synchronous")
                    if instance is None:
                        raise ProviderResolutionError(
                            f"provider factory returned no adapter: "
                            f"{capability.value}.{selection.name}"
                        )
                    self._instances[key] = instance
                values[capability] = instance
        return ResolvedProviderSnapshot(
            snapshot=canonical,
            llm=cast(StreamingLlm, values[Capability.LLM]),
            tts=cast(SpeechSynthesizer, values[Capability.TTS]),
            asr=cast(StreamingAsrFactory | None, values[Capability.ASR]),
            vision=cast(VisionAnalyzer | None, values[Capability.VISION]),
            voice_id=_clean_voice_id(voice_id),
        )

    async def warmup(self) -> None:
        """Warm already-resolved native engines without instantiating every option."""

        async with self._lock:
            instances = _unique_instances(
                (*self._owned_instances, *self._instances.values())
            )
        for instance in instances:
            warmup = getattr(instance, "warmup", None)
            if callable(warmup):
                result = warmup()
                if inspect.isawaitable(result):
                    await result

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            instances = _unique_instances(
                (*self._owned_instances, *self._instances.values())
            )
            self._instances.clear()
            self._owned_instances.clear()
        first_error: Exception | None = None
        for instance in reversed(instances):
            close = getattr(instance, "aclose", None)
            if not callable(close):
                continue
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                # One broken adapter must not strand sockets, native engines or
                # credentials owned by the remaining bindings during shutdown.
                first_error = first_error or exc
        if first_error is not None:
            raise first_error


def _public_values(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    cleaned: list[str] = []
    maximum = 80 if label == "voice" else 160
    for value in values:
        if not isinstance(value, str):
            raise ProviderResolutionError(f"{label} allowlist values must be strings")
        item = value.strip()
        if not item or len(item) > maximum or "\x00" in item:
            raise ProviderResolutionError(f"{label} allowlist contains an invalid value")
        if item not in cleaned:
            cleaned.append(item)
    return tuple(cleaned)


def _validate_public_config(
    selection: ProviderSelection,
    catalog: AvailableProvider,
) -> None:
    model = selection.config.get("model")
    voice = selection.config.get("voice")
    if model is not None and str(model) not in catalog.models:
        raise ProviderResolutionError(
            f"model is not allowlisted for "
            f"{selection.capability.value}.{selection.name}"
        )
    if voice is not None and str(voice) not in catalog.voices:
        raise ProviderResolutionError(
            f"voice is not allowlisted for "
            f"{selection.capability.value}.{selection.name}"
        )


def _validate_runtime_voice(
    snapshot: ProviderSnapshot,
    voice_id: str,
    bindings: dict[tuple[Capability, str], _RuntimeBinding],
) -> None:
    voice = _clean_voice_id(voice_id)
    if voice == "default":
        return
    selection = snapshot.resolve(Capability.TTS)
    binding = bindings[(Capability.TTS, selection.name)]
    if voice not in binding.catalog.voices:
        raise ProviderResolutionError(
            f"voice is not allowlisted for tts.{selection.name}"
        )


def _clean_voice_id(value: object) -> str:
    if not isinstance(value, str):
        raise ProviderResolutionError("voiceId must be a string")
    voice = value.strip()
    if not voice or len(voice) > 80 or "\x00" in voice:
        raise ProviderResolutionError("voiceId is invalid")
    return voice


def _instance_key(
    selection: ProviderSelection,
) -> tuple[Capability, str, tuple[tuple[str, str], ...]]:
    config = tuple(sorted((str(key), str(value)) for key, value in selection.config.items()))
    return selection.capability, selection.name, config


def _unique_instances(values: Any) -> list[object]:
    unique: list[object] = []
    seen: set[int] = set()
    for value in values:
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(value)
    return unique
