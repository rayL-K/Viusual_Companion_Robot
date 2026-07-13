"""One-turn context, LLM, and TTS orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from veyrasoul.personalization.model import AnimaProfile

from .context import ContextBundle
from .ports import SpeechSynthesisRequest, SpeechSynthesizer, StreamingLlm
from .prompt import build_messages
from .reply_pipeline import ReadyReplySegment, ReplyPipeline


class TurnService:
    def __init__(self, llm: StreamingLlm, tts: SpeechSynthesizer, stable_system_prompt: str) -> None:
        self.llm = llm
        self.tts = tts
        self.stable_system_prompt = stable_system_prompt.strip()
        if not self.stable_system_prompt:
            raise ValueError("stable_system_prompt must not be empty")

    async def generate(
        self,
        user_text: str,
        context: ContextBundle,
        profile: AnimaProfile,
    ) -> AsyncIterator[ReadyReplySegment]:
        history: list[dict[str, str]] = []
        for turn in context.recent_turns:
            user = str(turn.get("user") or turn.get("user_text") or "").strip()
            assistant = str(turn.get("assistant") or turn.get("assistant_text") or "").strip()
            if user:
                history.append({"role": "user", "content": user})
            if assistant:
                history.append({"role": "assistant", "content": assistant})
        affect = context.affect
        messages = build_messages(
            stable_system_prompt=self.stable_system_prompt,
            persona_prompt=profile.persona_markdown,
            response_constraint=profile.response_constraint(),
            history=history,
            user_text=user_text,
            visual_context=context.visual.prompt_summary() if context.visual else "",
            memory_context=[item.entry.body for item in context.memories],
            affect_context=(
                f"valence={affect.valence:.2f}, arousal={affect.arousal:.2f}, "
                f"affinity={affect.affinity:.2f}, trust={affect.trust:.2f}"
            ),
        )
        if profile.reply_delay_ms:
            await asyncio.sleep(profile.reply_delay_ms / 1000.0)

        async def synthesize(text: str) -> tuple[bytes, str]:
            return await self.tts.synthesize(
                SpeechSynthesisRequest(text=text, voice_id=profile.voice_id)
            )

        pipeline = ReplyPipeline(synthesize)
        limited_stream = _limit_stream(
            self.llm.stream_reply(messages),
            profile.max_reply_chars,
        )
        async for segment in pipeline.run(limited_stream):
            yield segment


async def _limit_stream(
    stream: AsyncIterator[str],
    maximum_chars: int,
) -> AsyncIterator[str]:
    remaining = max(1, int(maximum_chars))
    try:
        async for chunk in stream:
            value = str(chunk or "")
            if not value:
                continue
            clipped = value[:remaining]
            if clipped:
                remaining -= len(clipped)
                yield clipped
            if remaining <= 0:
                return
    finally:
        close = getattr(stream, "aclose", None)
        if callable(close):
            await close()
