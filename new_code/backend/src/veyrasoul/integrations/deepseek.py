"""Async DeepSeek streaming adapter with non-thinking low-latency defaults."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable, Mapping

import httpx


@dataclass(frozen=True, slots=True)
class DeepSeekConfig:
    api_key: str
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("DeepSeek api_key must not be empty")


class DeepSeekStreamClient:
    def __init__(self, config: DeepSeekConfig) -> None:
        self.config = config

    async def stream_reply(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        timeout = httpx.Timeout(
            connect=self.config.connect_timeout_seconds,
            read=self.config.read_timeout_seconds,
            write=10.0,
            pool=5.0,
        )
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
            "thinking": {"type": "disabled"},
        }
        async with httpx.AsyncClient(timeout=timeout, http2=True) as client:
            async with client.stream(
                "POST",
                f"{self.config.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    event = parse_sse_line(line)
                    if event is None:
                        continue
                    content = extract_content_delta(event)
                    if content:
                        yield content


def build_messages(
    *,
    stable_system_prompt: str,
    history: Iterable[Mapping[str, str]],
    user_text: str,
    visual_context: str = "",
    memory_context: Iterable[str] = (),
    affect_context: str = "",
) -> list[dict[str, str]]:
    """Keep stable prefix first so provider-side prefix caching can work."""

    messages = [{"role": "system", "content": stable_system_prompt.strip()}]
    for item in history:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:12_000]})
    context_parts = [f"视觉：{visual_context.strip()}" if visual_context.strip() else ""]
    memories = [str(value).strip() for value in memory_context if str(value).strip()]
    if memories:
        context_parts.append("相关记忆：\n- " + "\n- ".join(memories[:8]))
    if affect_context.strip():
        context_parts.append(f"角色当前情感连续状态：{affect_context.strip()}")
    dynamic_context = "\n".join(part for part in context_parts if part)
    final = user_text.strip()
    if dynamic_context:
        final = f"<current_context>\n{dynamic_context}\n</current_context>\n\n用户：{final}"
    messages.append({"role": "user", "content": final})
    return messages


def parse_sse_line(line: str) -> dict[str, Any] | None:
    normalized = line.strip()
    if not normalized or normalized.startswith(":") or not normalized.startswith("data:"):
        return None
    data = normalized[5:].strip()
    if data == "[DONE]":
        return None
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("DeepSeek SSE data must be an object")
    return value


def extract_content_delta(event: Mapping[str, Any]) -> str:
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, Mapping):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, Mapping):
        return ""
    return str(delta.get("content") or "")
