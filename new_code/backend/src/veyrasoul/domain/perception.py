"""Immutable perception snapshots used by dialogue context assembly."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class VisualSnapshot:
    frame_id: str
    observed_at_ms: int
    sequence: int
    semantic_caption: str = ""
    scene_caption: str = ""
    people: tuple[str, ...] = ()
    objects: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    face_emotions: Mapping[str, float] = field(default_factory=dict)
    confidence: float = 0.0

    def age_ms(self, now_ms: int | None = None) -> int:
        reference = int(time.time() * 1000) if now_ms is None else now_ms
        return max(0, reference - self.observed_at_ms)

    def is_fresh(self, max_age_ms: int, now_ms: int | None = None) -> bool:
        return self.age_ms(now_ms) <= max_age_ms

    def prompt_summary(self) -> str:
        parts = [part.strip() for part in (self.semantic_caption, self.scene_caption) if part.strip()]
        if self.people:
            parts.append("人物：" + "、".join(self.people))
        if self.actions:
            parts.append("动作：" + "、".join(self.actions))
        if self.objects:
            parts.append("物体：" + "、".join(self.objects))
        return "；".join(dict.fromkeys(parts))
