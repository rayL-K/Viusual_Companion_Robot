"""Convert dialogue and face emotion evidence into bounded affect cues."""

from __future__ import annotations

from collections.abc import Mapping

from .engine import AffectCue


_TEXT_CUES: tuple[tuple[tuple[str, ...], AffectCue], ...] = (
    (("我很开心", "我好开心", "好高兴", "太好了", "真棒"), AffectCue(0.34, 0.18, 0.05, 0.03, 0.02)),
    (("谢谢你", "多谢你", "有你真好"), AffectCue(0.22, 0.06, 0.0, 0.08, 0.08)),
    (("喜欢你", "爱你", "最喜欢你"), AffectCue(0.30, 0.16, 0.0, 0.13, 0.10)),
    (("我很难过", "我好难过", "心情不好", "我很伤心", "我想哭", "我很失落", "我很孤独", "我不开心"), AffectCue(-0.38, 0.10, -0.08, 0.02, 0.03)),
    (("我很生气", "气死我了", "烦死了", "我很愤怒"), AffectCue(-0.40, 0.36, 0.12, -0.02, -0.02)),
    (("我很害怕", "我好怕", "我很紧张", "我很焦虑", "我很担心"), AffectCue(-0.30, 0.32, -0.14, 0.02, 0.03)),
    (("好累", "累死了", "没精神"), AffectCue(-0.24, -0.08, -0.10, 0.02, 0.02)),
    (("我相信你", "信任你"), AffectCue(0.14, 0.02, 0.0, 0.06, 0.13)),
)

_FACE_CUES: dict[str, tuple[float, float, float]] = {
    "happy": (0.28, 0.14, 0.02),
    "happiness": (0.28, 0.14, 0.02),
    "开心": (0.28, 0.14, 0.02),
    "喜悦": (0.28, 0.14, 0.02),
    "sad": (-0.30, 0.04, -0.05),
    "sadness": (-0.30, 0.04, -0.05),
    "难过": (-0.30, 0.04, -0.05),
    "悲伤": (-0.30, 0.04, -0.05),
    "angry": (-0.32, 0.27, 0.08),
    "anger": (-0.32, 0.27, 0.08),
    "生气": (-0.32, 0.27, 0.08),
    "愤怒": (-0.32, 0.27, 0.08),
    "fear": (-0.28, 0.25, -0.10),
    "fearful": (-0.28, 0.25, -0.10),
    "害怕": (-0.28, 0.25, -0.10),
    "surprise": (0.04, 0.27, -0.02),
    "surprised": (0.04, 0.27, -0.02),
    "惊讶": (0.04, 0.27, -0.02),
    "disgust": (-0.28, 0.16, 0.06),
    "厌恶": (-0.28, 0.16, 0.06),
    "neutral": (0.0, -0.03, 0.0),
    "中性": (0.0, -0.03, 0.0),
}


def infer_affect_cue(
    user_text: str,
    face_emotions: Mapping[str, float] | None = None,
) -> AffectCue | None:
    """Fuse weak observable evidence; it changes state but never fabricates a reply."""

    cues = _text_evidence(str(user_text or ""))
    visual = _face_evidence(face_emotions or {})
    if visual is not None:
        cues.append(visual)
    if not cues:
        return None
    return AffectCue(
        valence=_clamp(sum(cue.valence for cue in cues), -0.55, 0.55),
        arousal=_clamp(sum(cue.arousal for cue in cues), -0.25, 0.55),
        dominance=_clamp(sum(cue.dominance for cue in cues), -0.30, 0.30),
        affinity=_clamp(sum(cue.affinity for cue in cues), -0.18, 0.22),
        trust=_clamp(sum(cue.trust for cue in cues), -0.18, 0.22),
    )


def _text_evidence(text: str) -> list[AffectCue]:
    normalized = "".join(text.lower().split())
    if not normalized:
        return []
    cues: list[AffectCue] = []
    for phrases, cue in _TEXT_CUES:
        if any(phrase in normalized for phrase in phrases):
            cues.append(cue)
    return cues


def _face_evidence(face_emotions: Mapping[str, float]) -> AffectCue | None:
    weighted_valence = 0.0
    weighted_arousal = 0.0
    weighted_dominance = 0.0
    total_confidence = 0.0
    for raw_name, raw_confidence in face_emotions.items():
        emotion = _FACE_CUES.get(str(raw_name).strip().lower())
        if emotion is None:
            continue
        confidence = _clamp(_as_float(raw_confidence), 0.0, 1.0)
        if confidence < 0.05:
            continue
        weighted_valence += emotion[0] * confidence
        weighted_arousal += emotion[1] * confidence
        weighted_dominance += emotion[2] * confidence
        total_confidence += confidence
    if total_confidence <= 0.0:
        return None
    normalization = max(1.0, total_confidence)
    return AffectCue(
        valence=weighted_valence / normalization,
        arousal=weighted_arousal / normalization,
        dominance=weighted_dominance / normalization,
    )


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
