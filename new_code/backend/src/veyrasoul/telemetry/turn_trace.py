"""Privacy-bounded, monotonic tracing for one realtime conversation turn."""

from __future__ import annotations

import json
import hashlib
import hmac
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol


_LOGGER = logging.getLogger(__name__)
_UNKNOWN = "unknown"


class TracePoint(str, Enum):
    ASR_FINAL = "asr.final"
    CONTEXT_READY = "context.ready"
    LLM_REQUEST = "llm.request"
    LLM_FIRST_VALID_DELTA = "llm.first_valid_delta"
    LLM_COMPLETED = "llm.completed"
    FIRST_SPEAKABLE_CLAUSE = "reply.first_speakable_clause"
    TTS_SUBMIT = "tts.submit"
    TTS_COMPLETED = "tts.completed"
    FIRST_REPLY_FRAME_SENT = "reply.first_frame_sent"
    TURN_COMPLETED = "turn.completed"
    TURN_CANCELLED = "turn.cancelled"
    TURN_ERROR = "turn.error"


class TraceStage(str, Enum):
    ASR = "asr"
    LLM = "llm"
    TTS = "tts"


@dataclass(frozen=True, slots=True)
class TurnTraceDimensions:
    session_id: str
    turn_id: str
    generation: int
    user_id: str
    anima_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _clean_identifier(self.session_id))
        object.__setattr__(self, "turn_id", _clean_identifier(self.turn_id))
        object.__setattr__(self, "generation", max(0, int(self.generation)))
        object.__setattr__(self, "user_id", _clean_identifier(self.user_id))
        object.__setattr__(self, "anima_id", _clean_identifier(self.anima_id))

    def to_dict(self) -> dict[str, object]:
        return {
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "generation": self.generation,
            "userId": self.user_id,
            "animaId": self.anima_id,
        }

    def anonymized(self, key: bytes) -> "TurnTraceDimensions":
        if len(key) < 32:
            raise ValueError("trace dimension HMAC key must contain at least 32 bytes")
        return replace(
            self,
            session_id=_dimension_digest(key, "session", self.session_id),
            turn_id=_dimension_digest(key, "turn", self.turn_id),
            user_id=_dimension_digest(key, "user", self.user_id),
            anima_id=_dimension_digest(key, "anima", self.anima_id),
        )


@dataclass(frozen=True, slots=True)
class ProviderModel:
    provider: str = _UNKNOWN
    model: str = _UNKNOWN

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _clean_dimension(self.provider))
        object.__setattr__(self, "model", _clean_dimension(self.model))

    def to_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "model": self.model}


@dataclass(frozen=True, slots=True)
class TraceProviders:
    asr: ProviderModel = field(default_factory=ProviderModel)
    llm: ProviderModel = field(default_factory=ProviderModel)
    tts: ProviderModel = field(default_factory=ProviderModel)

    def for_stage(self, stage: TraceStage | None) -> ProviderModel | None:
        if stage is None:
            return None
        return getattr(self, stage.value)

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {
            TraceStage.ASR.value: self.asr.to_dict(),
            TraceStage.LLM.value: self.llm.to_dict(),
            TraceStage.TTS.value: self.tts.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class TraceAttributes:
    """Allowlisted metadata only; conversational content has no representation here."""

    segment_index: int | None = None
    text_chars: int | None = None
    audio_bytes: int | None = None
    content_type: str = ""
    retrieval_timed_out: bool | None = None
    status: str = ""
    error_type: str = ""

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.segment_index is not None:
            payload["segmentIndex"] = max(0, int(self.segment_index))
        if self.text_chars is not None:
            payload["textChars"] = max(0, int(self.text_chars))
        if self.audio_bytes is not None:
            payload["audioBytes"] = max(0, int(self.audio_bytes))
        if self.content_type:
            payload["contentType"] = _clean_dimension(self.content_type)
        if self.retrieval_timed_out is not None:
            payload["retrievalTimedOut"] = bool(self.retrieval_timed_out)
        if self.status:
            payload["status"] = _clean_dimension(self.status)
        if self.error_type:
            payload["errorType"] = _clean_dimension(self.error_type)
        return payload


@dataclass(frozen=True, slots=True)
class TurnTracePoint:
    name: str
    monotonic_ns: int
    elapsed_ms: float
    provider: str = ""
    model: str = ""
    attributes: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "monotonicNs": self.monotonic_ns,
            "elapsedMs": self.elapsed_ms,
        }
        if self.provider:
            payload["provider"] = self.provider
            payload["model"] = self.model
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        return payload


@dataclass(frozen=True, slots=True)
class TurnTraceSnapshot:
    dimensions: TurnTraceDimensions
    providers: TraceProviders
    started_monotonic_ns: int
    closed_monotonic_ns: int | None
    outcome: str
    points: tuple[TurnTracePoint, ...]

    def to_dict(self) -> dict[str, object]:
        closed_ns = self.closed_monotonic_ns
        duration_ms = (
            round((closed_ns - self.started_monotonic_ns) / 1_000_000, 3)
            if closed_ns is not None
            else None
        )
        return {
            "schema": "veyrasoul.turn_trace.v1",
            "dimensions": self.dimensions.to_dict(),
            "providers": self.providers.to_dict(),
            "startedMonotonicNs": self.started_monotonic_ns,
            "closedMonotonicNs": closed_ns,
            "durationMs": duration_ms,
            "outcome": self.outcome,
            "points": [point.to_dict() for point in self.points],
        }


class TraceSink(Protocol):
    def emit(self, snapshot: TurnTraceSnapshot) -> None: ...


class NullTraceSink:
    def emit(self, snapshot: TurnTraceSnapshot) -> None:
        del snapshot


class JsonLogTraceSink:
    """Emit exactly one compact JSON log line for each closed turn trace."""

    def __init__(self, logger: logging.Logger, hmac_key: bytes | str | None = None) -> None:
        self._logger = logger
        if hmac_key is None:
            self._hmac_key = secrets.token_bytes(32)
        elif isinstance(hmac_key, str):
            self._hmac_key = hmac_key.encode("utf-8")
        else:
            self._hmac_key = bytes(hmac_key)
        if len(self._hmac_key) < 32:
            raise ValueError("trace dimension HMAC key must contain at least 32 bytes")

    def emit(self, snapshot: TurnTraceSnapshot) -> None:
        safe_snapshot = replace(
            snapshot,
            dimensions=snapshot.dimensions.anonymized(self._hmac_key),
        )
        record = {"event": "turn_trace", "trace": safe_snapshot.to_dict()}
        self._logger.info(
            "%s",
            json.dumps(record, ensure_ascii=False, separators=(",", ":")),
        )


@dataclass(frozen=True, slots=True)
class TraceSettings:
    sink: TraceSink = field(default_factory=NullTraceSink)
    providers: TraceProviders = field(default_factory=TraceProviders)

    def start(
        self,
        dimensions: TurnTraceDimensions,
    ) -> TurnTrace:
        return TurnTrace(
            dimensions=dimensions,
            providers=self.providers,
            sink=self.sink,
        )


class TurnTrace:
    """Mutable during one turn and immutable once its terminal point is emitted."""

    def __init__(
        self,
        *,
        dimensions: TurnTraceDimensions,
        providers: TraceProviders | None = None,
        sink: TraceSink | None = None,
        clock: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._dimensions = dimensions
        self._providers = providers or TraceProviders()
        self._sink = sink or NullTraceSink()
        self._clock = clock
        self._started_ns = int(clock())
        self._closed_ns: int | None = None
        self._outcome = "open"
        self._points: list[TurnTracePoint] = []

    @property
    def closed(self) -> bool:
        return self._closed_ns is not None

    def bind_generation(self, generation: int) -> None:
        if not self.closed:
            self._dimensions = replace(
                self._dimensions,
                generation=max(0, int(generation)),
            )

    def mark(
        self,
        point: TracePoint,
        *,
        stage: TraceStage | None = None,
        attributes: TraceAttributes | None = None,
    ) -> bool:
        return self.mark_at(
            point,
            int(self._clock()),
            stage=stage,
            attributes=attributes,
        )

    def mark_at(
        self,
        point: TracePoint,
        monotonic_ns: int,
        *,
        stage: TraceStage | None = None,
        attributes: TraceAttributes | None = None,
    ) -> bool:
        if self.closed:
            return False
        timestamp = max(0, int(monotonic_ns))
        if not self._points and timestamp < self._started_ns:
            self._started_ns = timestamp
        previous = self._points[-1].monotonic_ns if self._points else self._started_ns
        timestamp = max(previous, timestamp)
        provider = self._providers.for_stage(stage)
        self._points.append(
            TurnTracePoint(
                name=point.value,
                monotonic_ns=timestamp,
                elapsed_ms=round((timestamp - self._started_ns) / 1_000_000, 3),
                provider=provider.provider if provider else "",
                model=provider.model if provider else "",
                attributes=(attributes or TraceAttributes()).to_dict(),
            )
        )
        return True

    def complete(self) -> None:
        self._finish(TracePoint.TURN_COMPLETED, "completed")

    def cancel(self) -> None:
        self._finish(TracePoint.TURN_CANCELLED, "cancelled")

    def fail(self, error: BaseException | type[BaseException]) -> None:
        if isinstance(error, type):
            error_type = error.__name__
        else:
            error_type = type(error).__name__
        self._finish(
            TracePoint.TURN_ERROR,
            "error",
            TraceAttributes(error_type=error_type),
        )

    def snapshot(self) -> TurnTraceSnapshot:
        return TurnTraceSnapshot(
            dimensions=self._dimensions,
            providers=self._providers,
            started_monotonic_ns=self._started_ns,
            closed_monotonic_ns=self._closed_ns,
            outcome=self._outcome,
            points=tuple(self._points),
        )

    def _finish(
        self,
        terminal_point: TracePoint,
        outcome: str,
        attributes: TraceAttributes | None = None,
    ) -> None:
        if self.closed:
            return
        self.mark(terminal_point, attributes=attributes)
        last_ns = self._points[-1].monotonic_ns
        self._closed_ns = last_ns
        self._outcome = outcome
        try:
            self._sink.emit(self.snapshot())
        except Exception as exc:  # A telemetry outage must never fail a user turn.
            _LOGGER.warning("Turn trace sink failed (%s)", type(exc).__name__)


def _clean_dimension(value: object) -> str:
    text = str(value or "").strip()
    return text[:128] or _UNKNOWN


def _clean_identifier(value: object) -> str:
    text = str(value or "").strip()
    return text[:160] or _UNKNOWN


def _dimension_digest(key: bytes, label: str, value: str) -> str:
    digest = hmac.new(
        key,
        f"{label}\0{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    return f"h_{digest}"
