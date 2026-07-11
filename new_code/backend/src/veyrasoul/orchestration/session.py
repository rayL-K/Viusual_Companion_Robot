"""Per-session ownership, generation, and context lifecycle."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable

from veyrasoul.affect import AffectCue, AffectEngine, AffectState, infer_affect_cue
from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.memory.store import MemoryStore
from veyrasoul.runtime.latest_value import LatestValue

from .context import ContextAssembler, ContextBundle


class SessionKernel:
    def __init__(
        self,
        session_id: str,
        memory: MemoryStore,
        context: ContextAssembler,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        self.session_id = session_id
        self.memory = memory
        self.context = context
        self.visual: LatestValue[VisualSnapshot] = context.visual_slot
        self.affect = AffectEngine()
        self._monotonic_clock = monotonic_clock
        self._affect_updated_at = monotonic_clock()
        self._generation = 0
        self._lock = asyncio.Lock()
        self._recent_turns: deque[dict[str, object]] = deque(maxlen=8)
        self._recent_turns.extend(memory.recent_turns(session_id, limit=8))

    @property
    def generation(self) -> int:
        return self._generation

    async def begin_turn(self, user_text: str) -> tuple[int, ContextBundle]:
        normalized = str(user_text or "").strip()
        if not normalized:
            raise ValueError("user_text must not be empty")
        visual_version = await self.visual.snapshot()
        visual = visual_version.value
        face_emotions = (
            visual.face_emotions
            if visual is not None and visual.is_fresh(self.context.visual_max_age_ms)
            else {}
        )
        cue = infer_affect_cue(normalized, face_emotions)
        async with self._lock:
            self._generation += 1
            generation = self._generation
            recent = list(self._recent_turns)
            affect = self._advance_affect(cue)
        bundle = await self.context.assemble(normalized, recent, affect)
        return generation, bundle

    async def current_affect(self, generation: int | None = None) -> AffectState | None:
        """Return decayed state, or None when a caller belongs to an obsolete turn."""

        async with self._lock:
            if generation is not None and generation != self._generation:
                return None
            return self._advance_affect()

    async def cancel_current_turn(self) -> int:
        async with self._lock:
            self._generation += 1
            return self._generation

    async def complete_turn(
        self,
        generation: int,
        turn_id: str,
        user_text: str,
        assistant_text: str,
        cue: AffectCue | None = None,
    ) -> bool:
        async with self._lock:
            if generation != self._generation:
                return False
            self.memory.add_turn(self.session_id, turn_id, user_text, assistant_text)
            self._recent_turns.append(
                {"turn_id": turn_id, "user": user_text, "assistant": assistant_text}
            )
            self._advance_affect(cue)
            return True

    def _advance_affect(self, cue: AffectCue | None = None) -> AffectState:
        now = self._monotonic_clock()
        elapsed = max(0.0, now - self._affect_updated_at)
        self._affect_updated_at = now
        return self.affect.advance(elapsed, cue)
