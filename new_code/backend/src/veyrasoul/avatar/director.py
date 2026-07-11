"""Map continuous affect to a renderer-neutral avatar intent."""

from __future__ import annotations

from dataclasses import dataclass

from veyrasoul.affect.engine import AffectState


@dataclass(frozen=True, slots=True)
class AvatarIntent:
    expression: str
    motion: str
    gaze_strength: float
    body_tension: float
    smile: float
    eye_open: float
    speech_rate: float
    speech_pitch: float


class AvatarDirector:
    def intent_for(self, affect: AffectState, *, speaking: bool, listening: bool) -> AvatarIntent:
        if listening:
            expression, motion = "attentive", "listen"
        elif affect.arousal > 0.72 and affect.valence > 0.25:
            expression, motion = "delighted", "excited"
        elif affect.valence < -0.42:
            expression, motion = "concerned", "comfort"
        elif speaking:
            expression, motion = "warm", "talk"
        else:
            expression, motion = "soft", "idle"
        return AvatarIntent(
            expression=expression,
            motion=motion,
            gaze_strength=_clamp(0.55 + affect.affinity * 0.35, 0.25, 1.0),
            body_tension=_clamp(0.2 + affect.arousal * 0.65, 0.0, 1.0),
            smile=_clamp((affect.valence + 1.0) / 2.0, 0.0, 1.0),
            eye_open=_clamp(0.72 + affect.arousal * 0.28, 0.55, 1.0),
            speech_rate=_clamp(1.0 + (affect.arousal - 0.4) * 0.18, 0.88, 1.16),
            speech_pitch=_clamp(1.0 + affect.valence * 0.08 + affect.arousal * 0.04, 0.9, 1.13),
        )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
