"""Own all mutable user paths below one configurable data root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from veyrasoul.identity import AnimaId, UserId, storage_key


@dataclass(frozen=True, slots=True)
class DataLayout:
    root: Path
    legacy_memory_path: Path

    def __post_init__(self) -> None:
        root = self.root.expanduser().resolve()
        legacy = self.legacy_memory_path.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "legacy_memory_path", legacy)

    def anima_directory(self, user_id: UserId, anima_id: AnimaId) -> Path:
        user_key = storage_key("user", user_id.value)
        anima_key = storage_key("anima", anima_id.value)
        candidate = self.root / "users" / user_key / "animas" / anima_key
        return self._contained(candidate)

    def state_database(self, user_id: UserId, anima_id: AnimaId) -> Path:
        return self.anima_directory(user_id, anima_id) / "state.sqlite3"

    def persona_file(self, user_id: UserId, anima_id: AnimaId) -> Path:
        return self.anima_directory(user_id, anima_id) / "Anima.md"

    def _contained(self, candidate: Path) -> Path:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("用户数据路径越界") from exc
        return resolved
