"""Deterministic long-term fact curation with provenance and conflict control."""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from .store import MemoryStore


_SOURCE_RELIABILITY = {
    "explicit": 1.0,
    "document": 0.95,
    "conversation": 0.85,
    "inference": 0.65,
    "vision": 0.55,
}


@dataclass(frozen=True, slots=True)
class FactCandidate:
    """A structured candidate extracted from one traceable observation."""

    subject: str
    predicate: str
    value: str
    confidence: float
    source: str
    evidence_kind: str = "conversation"
    importance: float | None = None
    observed_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class CuratedFact:
    fact_id: int
    action: str
    active_value: str
    effective_confidence: float


class MemoryCurator:
    """Keep one stable fact while retaining supporting and conflicting evidence."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        revision_margin: float = 0.08,
        explicit_revision_floor: float = 0.72,
    ) -> None:
        self.store = store
        self.revision_margin = max(0.0, min(float(revision_margin), 1.0))
        self.explicit_revision_floor = max(0.0, min(float(explicit_revision_floor), 1.0))

    def curate(self, candidate: FactCandidate) -> CuratedFact:
        subject = _normalize_text(candidate.subject, "subject", 120)
        predicate = _normalize_text(candidate.predicate, "predicate", 120)
        value = _normalize_value(candidate.value)
        source = _normalize_text(candidate.source, "source", 120)
        kind = str(candidate.evidence_kind or "").strip().lower()
        if kind not in _SOURCE_RELIABILITY:
            allowed = ", ".join(sorted(_SOURCE_RELIABILITY))
            raise ValueError(f"evidence_kind must be one of: {allowed}")

        raw_confidence = _clamp(candidate.confidence)
        effective_confidence = raw_confidence * _SOURCE_RELIABILITY[kind]
        observed_at_ms = (
            int(time.time() * 1000)
            if candidate.observed_at_ms is None
            else int(candidate.observed_at_ms)
        )
        importance = (
            _default_importance(predicate)
            if candidate.importance is None
            else _clamp(candidate.importance)
        )
        active = self.store.active_fact(subject, predicate)

        if active is None:
            fact_id = self._write(
                subject,
                predicate,
                value,
                source,
                kind,
                raw_confidence,
                effective_confidence,
                importance,
                observed_at_ms,
            )
            return CuratedFact(fact_id, "created", value, effective_confidence)

        active_value = str(active["value"])
        if _canonical(active_value) == _canonical(value):
            fact_id = self._write(
                subject,
                predicate,
                active_value,
                source,
                kind,
                raw_confidence,
                effective_confidence,
                importance,
                observed_at_ms,
            )
            merged_confidence = max(float(active["confidence"]), effective_confidence)
            return CuratedFact(fact_id, "reinforced", active_value, merged_confidence)

        current_confidence = float(active["confidence"])
        explicit_override = (
            kind == "explicit" and effective_confidence >= self.explicit_revision_floor
        )
        if explicit_override or effective_confidence >= current_confidence + self.revision_margin:
            fact_id = self._write(
                subject,
                predicate,
                value,
                source,
                kind,
                raw_confidence,
                effective_confidence,
                importance,
                observed_at_ms,
            )
            return CuratedFact(fact_id, "revised", value, effective_confidence)

        self.store.record_fact_evidence(
            fact_id=int(active["id"]),
            claimed_value=value,
            source=source,
            evidence_kind=kind,
            raw_confidence=raw_confidence,
            effective_confidence=effective_confidence,
            observed_at_ms=observed_at_ms,
            decision="conflict_ignored",
        )
        return CuratedFact(
            int(active["id"]), "conflict_ignored", active_value, current_confidence
        )

    def curate_many(self, candidates: Iterable[FactCandidate]) -> list[CuratedFact]:
        """Curate in observation order so revisions remain explainable."""

        return [self.curate(candidate) for candidate in candidates]

    def _write(
        self,
        subject: str,
        predicate: str,
        value: str,
        source: str,
        kind: str,
        raw_confidence: float,
        effective_confidence: float,
        importance: float,
        observed_at_ms: int,
    ) -> int:
        return self.store.upsert_fact(
            subject=subject,
            predicate=predicate,
            value=value,
            confidence=effective_confidence,
            source=source,
            observed_at_ms=observed_at_ms,
            importance=importance,
            evidence_kind=kind,
            raw_confidence=raw_confidence,
        )


def _normalize_text(value: str, name: str, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized[:max_length]


def _normalize_value(value: str) -> str:
    normalized = _normalize_text(value, "value", 2_000)
    normalized = normalized.rstrip("。.!！?？;；")
    if not normalized:
        raise ValueError("value must not be empty")
    return normalized


def _canonical(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def _default_importance(predicate: str) -> float:
    preference_markers = ("喜欢", "偏好", "讨厌", "希望", "称呼", "习惯")
    identity_markers = ("姓名", "名字", "生日", "身份", "关系")
    if any(marker in predicate for marker in identity_markers):
        return 0.9
    if any(marker in predicate for marker in preference_markers):
        return 0.85
    return 0.65


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
