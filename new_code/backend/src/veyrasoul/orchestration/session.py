"""Per-session ownership, generation, and context lifecycle."""

from __future__ import annotations

import asyncio
from collections import deque

from veyrasoul.affect.engine import AffectCue, AffectEngine
from veyrasoul.domain.perception import VisualSnapshot
from veyrasoul.memory.store import MemoryStore
from veyrasoul.runtime.latest_value import LatestValue

from .context import ContextAssembler, ContextBundle


class SessionKernel:
    def __init__(self, session_id: str, memory: MemoryStore, context: ContextAssembler) -> None:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        self.session_id = session_id
        self.memory = memory
        self.context = context
        self.visual: LatestValue[VisualSnapshot] = context.visual_slot
        self.affect = AffectEngine()
        self._generation = 0
        self._lock = asyncio.Lock()
        self._recent_turns: deque[dict[str, object]] = deque(maxlen=8)

    @property
    def generation(self) -> int:
        return self._generation

    async def begin_turn(self, user_text: str) -> tuple[int, ContextBundle]:
        normalized = str(user_text or "").strip()
        if not normalized:
            raise ValueError("user_text must not be empty")
        async with self._lock:
            self._generation += 1
            generation = self._generation
            recent = list(self._recent_turns)
            affect = self.affect.state
        bundle = await self.context.assemble(normalized, recent, affect)
        return generation, bundle

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
            self.affect.advance(0.0, cue)
            return True
