"""One-turn context, LLM, and TTS orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator

from veyrasoul.integrations.deepseek import build_messages

from .context import ContextBundle
from .ports import SpeechSynthesizer, StreamingLlm
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
            history=history,
            user_text=user_text,
            visual_context=context.visual.prompt_summary() if context.visual else "",
            memory_context=[item.entry.body for item in context.memories],
            affect_context=(
                f"valence={affect.valence:.2f}, arousal={affect.arousal:.2f}, "
                f"affinity={affect.affinity:.2f}, trust={affect.trust:.2f}"
            ),
        )
        pipeline = ReplyPipeline(self.tts.synthesize)
        async for segment in pipeline.run(self.llm.stream_reply(messages)):
            yield segment
