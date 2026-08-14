"""One-turn context, LLM, and TTS orchestration."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from veyrasoul.personalization.model import AnimaProfile
from veyrasoul.telemetry import (
    TraceAttributes,
    TracePoint,
    TraceStage,
    TurnTrace,
)

from .context import ContextBundle
from .ports import (
    SpeechSynthesisRequest,
    SpeechSynthesisStream,
    SpeechSynthesizer,
    StreamingLlm,
)
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
        *,
        trace: TurnTrace | None = None,
        stream_audio: bool = False,
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
            rag_context=context.rag_context,
            affect_context=(
                f"valence={affect.valence:.2f}, arousal={affect.arousal:.2f}, "
                f"affinity={affect.affinity:.2f}, trust={affect.trust:.2f}"
            ),
        )
        if profile.reply_delay_ms:
            await asyncio.sleep(profile.reply_delay_ms / 1000.0)

        segment_index = 0

        async def synthesize(text: str) -> tuple[bytes, str] | SpeechSynthesisStream:
            nonlocal segment_index
            current_index = segment_index
            segment_index += 1
            common = TraceAttributes(
                segment_index=current_index,
                text_chars=len(text),
            )
            if trace is not None:
                if current_index == 0:
                    trace.mark(
                        TracePoint.FIRST_SPEAKABLE_CLAUSE,
                        attributes=TraceAttributes(text_chars=len(text)),
                    )
                trace.mark(TracePoint.TTS_SUBMIT, stage=TraceStage.TTS, attributes=common)
            request = SpeechSynthesisRequest(text=text, voice_id=profile.voice_id)

            def mark_completed(
                status: str,
                *,
                audio_bytes: int = 0,
                content_type: str = "",
                error_type: str = "",
            ) -> None:
                if trace is not None:
                    trace.mark(
                        TracePoint.TTS_COMPLETED,
                        stage=TraceStage.TTS,
                        attributes=TraceAttributes(
                            segment_index=current_index,
                            text_chars=len(text),
                            audio_bytes=audio_bytes,
                            content_type=content_type,
                            status=status,
                            error_type=error_type,
                        ),
                    )

            if stream_audio:
                stream_synthesize = getattr(self.tts, "stream_synthesize", None)
                if callable(stream_synthesize):
                    try:
                        stream = await stream_synthesize(request)
                    except asyncio.CancelledError:
                        mark_completed("cancelled", error_type="CancelledError")
                        raise
                    except Exception as exc:
                        mark_completed("error", error_type=type(exc).__name__)
                        raise
                    if not isinstance(stream, SpeechSynthesisStream):
                        mark_completed("error", error_type="TypeError")
                        raise TypeError("stream_synthesize must return SpeechSynthesisStream")
                    return SpeechSynthesisStream(
                        stream.format,
                        _trace_speech_stream(stream, mark_completed),
                    )

            status = "closed"
            error_type = ""
            audio = b""
            content_type = ""
            try:
                audio, content_type = await self.tts.synthesize(request)
            except asyncio.CancelledError:
                status = "cancelled"
                error_type = "CancelledError"
                raise
            except Exception as exc:
                status = "error"
                error_type = type(exc).__name__
                raise
            else:
                status = "completed"
                return audio, content_type
            finally:
                mark_completed(
                    status,
                    audio_bytes=len(audio),
                    content_type=content_type,
                    error_type=error_type,
                )

        pipeline = ReplyPipeline(synthesize)
        if trace is not None:
            trace.mark(TracePoint.LLM_REQUEST, stage=TraceStage.LLM)
        limited_stream = _limit_stream(
            _trace_llm_stream(self.llm.stream_reply(messages), trace),
            profile.max_reply_chars,
        )
        async for segment in pipeline.run(limited_stream):
            yield segment


async def _trace_speech_stream(
    stream: SpeechSynthesisStream,
    mark_completed,
) -> AsyncIterator[bytes]:
    status = "closed"
    error_type = ""
    audio_bytes = 0
    try:
        async for chunk in stream.chunks:
            payload = bytes(chunk)
            if not payload:
                continue
            audio_bytes += len(payload)
            yield payload
    except asyncio.CancelledError:
        status = "cancelled"
        error_type = "CancelledError"
        raise
    except Exception as exc:
        status = "error"
        error_type = type(exc).__name__
        raise
    else:
        status = "completed"
    finally:
        with contextlib.suppress(Exception):
            await stream.aclose()
        mark_completed(
            status,
            audio_bytes=audio_bytes,
            content_type=stream.format.content_type,
            error_type=error_type,
        )


async def _trace_llm_stream(
    stream: AsyncIterator[str],
    trace: TurnTrace | None,
) -> AsyncIterator[str]:
    first_delta_seen = False
    status = "closed"
    error_type = ""
    try:
        async for chunk in stream:
            value = str(chunk or "")
            if trace is not None and value.strip() and not first_delta_seen:
                first_delta_seen = True
                trace.mark(
                    TracePoint.LLM_FIRST_VALID_DELTA,
                    stage=TraceStage.LLM,
                    attributes=TraceAttributes(text_chars=len(value)),
                )
            yield value
    except asyncio.CancelledError:
        status = "cancelled"
        error_type = "CancelledError"
        raise
    except Exception as exc:
        status = "error"
        error_type = type(exc).__name__
        raise
    else:
        status = "completed"
    finally:
        if trace is not None:
            trace.mark(
                TracePoint.LLM_COMPLETED,
                stage=TraceStage.LLM,
                attributes=TraceAttributes(status=status, error_type=error_type),
            )


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
