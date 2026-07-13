"""Provider-neutral construction of stable and per-Anima dialogue context."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


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
) -> list[dict[str, str]]:
    """Keep the provider-cacheable prefix ahead of dynamic account context."""

    messages = [{"role": "system", "content": stable_system_prompt.strip()}]
    if persona_prompt.strip():
        messages.append(
            {
                "role": "system",
                "content": f"<anima_persona>\n{persona_prompt.strip()}\n</anima_persona>",
            }
        )
    if response_constraint.strip():
        messages.append(
            {
                "role": "system",
                "content": f"<response_constraint>\n{response_constraint.strip()}\n</response_constraint>",
            }
        )
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
