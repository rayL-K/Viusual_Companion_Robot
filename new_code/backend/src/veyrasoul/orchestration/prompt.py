"""Provider-neutral construction of bounded per-Anima dialogue context."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class PromptBudget:
    """Character budgets keep provider latency predictable without a tokenizer dependency."""

    total_chars: int = 8_000
    stable_system_chars: int = 800
    persona_chars: int = 1_800
    response_constraint_chars: int = 300
    history_chars: int = 2_800
    history_message_chars: int = 900
    visual_chars: int = 700
    memory_chars: int = 800
    affect_chars: int = 180
    user_chars: int = 1_000

    def __post_init__(self) -> None:
        for field in fields(self):
            name = field.name
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.total_chars < 2:
            raise ValueError("total_chars must leave room for system and user messages")


def build_messages(
    *,
    stable_system_prompt: str,
    history: Iterable[Mapping[str, str]],
    user_text: str,
    persona_prompt: str = "",
    response_constraint: str = "",
    visual_context: str = "",
    memory_context: Iterable[str] = (),
    affect_context: str = "",
    budget: PromptBudget | None = None,
) -> list[dict[str, str]]:
    """Keep a cacheable prefix and a hard-bounded, newest-first context suffix."""

    limits = budget or PromptBudget()
    stable = _clip(stable_system_prompt, limits.stable_system_chars)
    if not stable:
        raise ValueError("stable_system_prompt must not be empty")
    messages = [{"role": "system", "content": stable}]
    persona = _clip(persona_prompt, limits.persona_chars)
    if persona:
        messages.append(
            {
                "role": "system",
                "content": f"<anima_persona>\n{persona}\n</anima_persona>",
            }
        )
    constraint = _clip(response_constraint, limits.response_constraint_chars)
    if constraint:
        messages.append(
            {
                "role": "system",
                "content": f"<response_constraint>\n{constraint}\n</response_constraint>",
            }
        )

    visual = _clip(visual_context, limits.visual_chars)
    context_parts = [f"视觉：{visual}" if visual else ""]
    memories = _bounded_values(memory_context, limits.memory_chars)
    if memories:
        context_parts.append("相关记忆：\n- " + "\n- ".join(memories))
    affect = _clip(affect_context, limits.affect_chars)
    if affect:
        context_parts.append(f"角色当前情感连续状态：{affect}")
    dynamic_context = "\n".join(part for part in context_parts if part)
    final = _clip(user_text, limits.user_chars)
    if not final:
        raise ValueError("user_text must not be empty")
    if dynamic_context:
        final = f"<current_context>\n{dynamic_context}\n</current_context>\n\n用户：{final}"

    fixed_chars = sum(len(item["content"]) for item in messages) + len(final)
    history_budget = min(limits.history_chars, max(0, limits.total_chars - fixed_chars))
    messages.extend(_bounded_history(history, history_budget, limits.history_message_chars))
    messages.append({"role": "user", "content": final})

    return _enforce_total_budget(messages, limits.total_chars)


def message_char_count(messages: Iterable[Mapping[str, str]]) -> int:
    return sum(len(str(item.get("content") or "")) for item in messages)


def _enforce_total_budget(
    messages: list[dict[str, str]],
    total_chars: int,
) -> list[dict[str, str]]:
    """Trim optional context before the two required messages, never exceeding the cap."""

    if len(messages) < 2:
        raise ValueError("prompt must contain system and user messages")
    overflow = message_char_count(messages) - total_chars
    if overflow <= 0:
        return messages

    # Persona/constraints are useful but optional. Remove them before touching
    # the stable policy or the user's current utterance.
    while overflow > 0 and len(messages) > 2 and messages[1]["role"] == "system":
        overflow -= len(messages[1]["content"])
        messages.pop(1)

    # History is already newest-bounded; if unusual markup still overflowed,
    # discard its oldest messages as complete role/content pairs.
    while overflow > 0 and len(messages) > 2:
        overflow -= len(messages[1]["content"])
        messages.pop(1)

    if overflow > 0:
        final = messages[-1]["content"]
        keep = max(1, len(final) - overflow)
        messages[-1] = {"role": "user", "content": _clip(final, keep)}
        overflow = message_char_count(messages) - total_chars
    if overflow > 0:
        stable = messages[0]["content"]
        keep = max(1, len(stable) - overflow)
        messages[0] = {"role": "system", "content": _clip(stable, keep)}

    if message_char_count(messages) > total_chars:
        raise ValueError("total_chars is too small for required prompt messages")
    return messages


def _bounded_history(
    history: Iterable[Mapping[str, str]],
    budget: int,
    per_message: int,
) -> list[dict[str, str]]:
    if budget <= 0:
        return []
    candidates: list[dict[str, str]] = []
    for item in history:
        role = str(item.get("role") or "").strip()
        content = _clip(str(item.get("content") or ""), per_message)
        if role in {"user", "assistant"} and content:
            candidates.append({"role": role, "content": content})
    selected: list[dict[str, str]] = []
    used = 0
    for item in reversed(candidates):
        size = len(item["content"])
        if used + size > budget:
            break
        selected.append(item)
        used += size
    selected.reverse()
    while len(selected) > 1 and selected[0]["role"] == "assistant":
        selected.pop(0)
    return selected


def _bounded_values(values: Iterable[str], budget: int) -> list[str]:
    selected: list[str] = []
    used = 0
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        separator = 2 if selected else 0
        remaining = budget - used - separator
        if remaining <= 0:
            break
        clipped = _clip(value, remaining)
        if clipped:
            selected.append(clipped)
            used += len(clipped) + separator
        if len(value) > remaining:
            break
    return selected


def _clip(value: object, limit: int) -> str:
    normalized = str(value or "").strip()
    if len(normalized) <= limit:
        return normalized
    marker = "\n…\n"
    if limit <= len(marker):
        return normalized[:limit]
    available = limit - len(marker)
    head = max(1, int(available * 0.75))
    tail = available - head
    return f"{normalized[:head]}{marker}{normalized[-tail:]}" if tail else normalized[:limit]
