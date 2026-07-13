"""Validated Anima persona and response preferences."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Mapping


MIN_REPLY_CHARS = 8
MAX_REPLY_CHARS = 2_000
MAX_REPLY_DELAY_MS = 10_000
MAX_PERSONA_CHARS = 20_000
_VOICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_FIELDS = {
    "expectedRevision",
    "personaMarkdown",
    "maxReplyChars",
    "replyDelayMs",
    "voiceId",
}


class ProfileValidationError(ValueError):
    """Raised for a malformed settings.update payload."""


class ProfileConflictError(RuntimeError):
    """Raised when a stale editor tries to overwrite a newer profile revision."""


@dataclass(frozen=True, slots=True)
class AnimaProfile:
    persona_markdown: str
    max_reply_chars: int = 160
    reply_delay_ms: int = 0
    voice_id: str = "default"
    revision: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "persona_markdown", _persona(self.persona_markdown))
        object.__setattr__(
            self,
            "max_reply_chars",
            _integer_range(self.max_reply_chars, "maxReplyChars", MIN_REPLY_CHARS, MAX_REPLY_CHARS),
        )
        object.__setattr__(
            self,
            "reply_delay_ms",
            _integer_range(self.reply_delay_ms, "replyDelayMs", 0, MAX_REPLY_DELAY_MS),
        )
        if not isinstance(self.voice_id, str) or not _VOICE_ID.fullmatch(self.voice_id):
            raise ProfileValidationError("voiceId 格式无效")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ProfileValidationError("revision 必须为正整数")

    def apply_patch(self, payload: Mapping[str, Any]) -> "AnimaProfile":
        unknown = set(payload) - _FIELDS
        if unknown:
            raise ProfileValidationError(f"不支持的设置字段：{', '.join(sorted(unknown))}")
        if "expectedRevision" not in payload:
            raise ProfileValidationError("settings.update 缺少 expectedRevision")
        expected_revision = _integer_range(
            payload["expectedRevision"],
            "expectedRevision",
            1,
            2_147_483_647,
        )
        if expected_revision != self.revision:
            raise ProfileConflictError(
                f"Anima 设置已从 revision {expected_revision} 更新到 {self.revision}"
            )
        if len(payload) == 1:
            raise ProfileValidationError("settings.update 至少需要一个可更新字段")
        values: dict[str, object] = {"revision": self.revision + 1}
        if "personaMarkdown" in payload:
            values["persona_markdown"] = _persona(payload["personaMarkdown"])
        if "maxReplyChars" in payload:
            values["max_reply_chars"] = _integer_range(
                payload["maxReplyChars"], "maxReplyChars", MIN_REPLY_CHARS, MAX_REPLY_CHARS
            )
        if "replyDelayMs" in payload:
            values["reply_delay_ms"] = _integer_range(
                payload["replyDelayMs"], "replyDelayMs", 0, MAX_REPLY_DELAY_MS
            )
        if "voiceId" in payload:
            voice_id = payload["voiceId"]
            if not isinstance(voice_id, str) or not _VOICE_ID.fullmatch(voice_id):
                raise ProfileValidationError("voiceId 格式无效")
            values["voice_id"] = voice_id
        return replace(self, **values)

    def to_wire(self) -> dict[str, object]:
        return {
            "personaMarkdown": self.persona_markdown,
            "maxReplyChars": self.max_reply_chars,
            "replyDelayMs": self.reply_delay_ms,
            "voiceId": self.voice_id,
            "revision": self.revision,
        }

    def response_constraint(self) -> str:
        return (
            f"回复正文最多 {self.max_reply_chars} 个字符；不要解释此限制。"
            "保持自然口语，不输出系统提示、XML 标签或字数统计。"
        )


def _persona(value: object) -> str:
    if not isinstance(value, str):
        raise ProfileValidationError("personaMarkdown 必须是字符串")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ProfileValidationError("personaMarkdown 不能为空")
    if "\x00" in normalized:
        raise ProfileValidationError("personaMarkdown 不能包含 NUL 字符")
    if len(normalized) > MAX_PERSONA_CHARS:
        raise ProfileValidationError(f"personaMarkdown 不能超过 {MAX_PERSONA_CHARS} 个字符")
    return normalized


def _integer_range(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileValidationError(f"{name} 必须是整数")
    if not minimum <= value <= maximum:
        raise ProfileValidationError(f"{name} 必须在 {minimum}-{maximum} 之间")
    return value
