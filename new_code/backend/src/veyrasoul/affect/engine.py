"""Continuous emotional state with decay and relationship continuity."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AffectState:
    valence: float = 0.0
    arousal: float = 0.15
    dominance: float = 0.0
    affinity: float = 0.25
    trust: float = 0.2


@dataclass(frozen=True, slots=True)
class AffectCue:
    valence: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0
    affinity: float = 0.0
    trust: float = 0.0
    strength: float = 1.0


class AffectEngine:
    def __init__(self, initial: AffectState | None = None) -> None:
        self._state = initial or AffectState()

    @property
    def state(self) -> AffectState:
        return self._state

    def advance(self, elapsed_seconds: float, cue: AffectCue | None = None) -> AffectState:
        elapsed = max(0.0, float(elapsed_seconds))
        emotional_decay = math.exp(-elapsed / 45.0)
        relationship_decay = math.exp(-elapsed / (14 * 86_400.0))
        current = self._state
        cue = cue or AffectCue(strength=0.0)
        strength = _clamp(cue.strength, 0.0, 1.0)
        self._state = AffectState(
            valence=_clamp(current.valence * emotional_decay + cue.valence * strength, -1.0, 1.0),
            arousal=_clamp(
                0.15 + (current.arousal - 0.15) * emotional_decay + cue.arousal * strength,
                0.0,
                1.0,
            ),
            dominance=_clamp(current.dominance * emotional_decay + cue.dominance * strength, -1.0, 1.0),
            affinity=_clamp(current.affinity * relationship_decay + cue.affinity * strength, -1.0, 1.0),
            trust=_clamp(current.trust * relationship_decay + cue.trust * strength, -1.0, 1.0),
        )
        return self._state


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
