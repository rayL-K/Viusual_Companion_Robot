"""SQLite-backed episodic, semantic, and document memory store."""

from __future__ import annotations

import json
import re
import sqlite3
import struct
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    id: int
    kind: str
    title: str
    body: str
    source: str
    importance: float
    observed_at_ms: int
    embedding: tuple[float, ...] = ()
    metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    kind: str
    title: str
    body: str
    source: str
    importance: float = 0.5
    observed_at_ms: int | None = None
    embedding: Sequence[float] | None = None
    metadata: dict[str, object] | None = None


class MemoryStore:
    """Use WAL, revisioned facts, and FTS5 without an extra database process."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add_entry(
        self,
        *,
        kind: str,
        title: str,
        body: str,
        source: str,
        importance: float = 0.5,
        observed_at_ms: int | None = None,
        embedding: Sequence[float] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> int:
        with self.connection(immediate=True) as connection:
            return self._insert_entry(
                connection,
                kind=_required_text(kind, "kind", 40),
                title=str(title or "").strip()[:240],
                body=_required_text(body, "body", 12_000),
                source=_required_text(source, "source", 120),
                importance=_clamp(float(importance), 0.0, 1.0),
                observed_at_ms=(
                    int(time.time() * 1000)
                    if observed_at_ms is None
                    else int(observed_at_ms)
                ),
                embedding=embedding,
                metadata=metadata,
            )

    def add_entries(self, drafts: Sequence[MemoryDraft]) -> list[int]:
        """Ingest a document or import batch in one transaction."""

        if not drafts:
            return []
        inserted: list[int] = []
        now_ms = int(time.time() * 1000)
        with self.connection(immediate=True) as connection:
            for draft in drafts:
                inserted.append(
                    self._insert_entry(
                        connection,
                        kind=_required_text(draft.kind, "kind", 40),
                        title=str(draft.title or "").strip()[:240],
                        body=_required_text(draft.body, "body", 12_000),
                        source=_required_text(draft.source, "source", 120),
                        importance=_clamp(float(draft.importance), 0.0, 1.0),
                        observed_at_ms=draft.observed_at_ms or now_ms,
                        embedding=draft.embedding,
                        metadata=draft.metadata,
                    )
                )
        return inserted

    def add_turn(self, session_id: str, turn_id: str, user_text: str, assistant_text: str) -> int:
        with self.connection(immediate=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO turns(session_id, turn_id, user_text, assistant_text, created_at_ms)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    _required_text(session_id, "session_id", 100),
                    _required_text(turn_id, "turn_id", 100),
                    _required_text(user_text, "user_text", 8_000),
                    _required_text(assistant_text, "assistant_text", 12_000),
                    int(time.time() * 1000),
                ),
            )
            return int(cursor.lastrowid)

    def recent_turns(self, session_id: str, limit: int = 8) -> list[dict[str, object]]:
        safe_limit = max(1, min(int(limit), 30))
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT turn_id, user_text, assistant_text, created_at_ms
                FROM turns WHERE session_id=? ORDER BY id DESC LIMIT ?
                """,
                (session_id, safe_limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def copy_session_to(self, target: "MemoryStore", session_id: str) -> int:
        """Idempotently migrate one legacy session without exposing other users' rows."""

        normalized = _required_text(session_id, "session_id", 100)
        if self.db_path.resolve() == target.db_path.resolve():
            return 0
        with self.connection() as source:
            rows = source.execute(
                """
                SELECT session_id, turn_id, user_text, assistant_text, created_at_ms
                FROM turns WHERE session_id=? ORDER BY id
                """,
                (normalized,),
            ).fetchall()
        if not rows:
            return 0
        with target.connection(immediate=True) as destination:
            before = destination.total_changes
            destination.executemany(
                """
                INSERT OR IGNORE INTO turns(
                    session_id, turn_id, user_text, assistant_text, created_at_ms
                ) VALUES(?, ?, ?, ?, ?)
                """,
                [tuple(row) for row in rows],
            )
            return destination.total_changes - before

    def upsert_fact(
        self,
        *,
        subject: str,
        predicate: str,
        value: str,
        confidence: float,
        source: str,
        observed_at_ms: int | None = None,
        importance: float | None = None,
        evidence_kind: str = "direct",
        raw_confidence: float | None = None,
    ) -> int:
        subject = _required_text(subject, "subject", 120)
        predicate = _required_text(predicate, "predicate", 120)
        value = _required_text(value, "value", 2_000)
        source = _required_text(source, "source", 120)
        evidence_kind = _required_text(evidence_kind, "evidence_kind", 40)
        observed = int(time.time() * 1000) if observed_at_ms is None else int(observed_at_ms)
        confidence = _clamp(float(confidence), 0.0, 1.0)
        raw_confidence = _clamp(
            confidence if raw_confidence is None else float(raw_confidence), 0.0, 1.0
        )
        memory_importance = _clamp(
            confidence if importance is None else float(importance), 0.0, 1.0
        )
        with self.connection(immediate=True) as connection:
            current = connection.execute(
                """
                SELECT f.id, f.value, f.confidence, f.source, f.observed_at_ms, f.entry_id,
                       e.importance, e.metadata_json
                FROM facts f JOIN memory_entries e ON e.id=f.entry_id
                WHERE f.subject=? AND f.predicate=? AND f.active=1
                ORDER BY f.id DESC LIMIT 1
                """,
                (subject, predicate),
            ).fetchone()
            if current and current["value"] == value:
                merged_confidence = max(float(current["confidence"]), confidence)
                merged_importance = max(float(current["importance"]), memory_importance)
                merged_observed = max(int(current["observed_at_ms"]), observed)
                dominant_source = (
                    source if confidence >= float(current["confidence"]) else str(current["source"])
                )
                metadata = _metadata_with_source(current["metadata_json"], source)
                connection.execute(
                    "UPDATE facts SET confidence=?, source=?, observed_at_ms=? WHERE id=?",
                    (merged_confidence, dominant_source, merged_observed, current["id"]),
                )
                connection.execute(
                    """
                    UPDATE memory_entries
                    SET source=?, importance=?, observed_at_ms=?, metadata_json=? WHERE id=?
                    """,
                    (
                        dominant_source,
                        merged_importance,
                        merged_observed,
                        json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                        current["entry_id"],
                    ),
                )
                self._insert_fact_evidence(
                    connection,
                    fact_id=int(current["id"]),
                    claimed_value=value,
                    source=source,
                    evidence_kind=evidence_kind,
                    raw_confidence=raw_confidence,
                    effective_confidence=confidence,
                    observed_at_ms=observed,
                    decision="reinforced",
                )
                return int(current["id"])

            previous_id = int(current["id"]) if current else None
            if current:
                connection.execute("UPDATE facts SET active=0 WHERE id=?", (previous_id,))
                connection.execute("UPDATE memory_entries SET active=0 WHERE id=?", (current["entry_id"],))

            entry_id = self._insert_entry(
                connection,
                kind="fact",
                title=f"{subject} · {predicate}",
                body=f"{subject}{predicate}：{value}",
                source=source,
                importance=memory_importance,
                observed_at_ms=observed,
                embedding=None,
                metadata={
                    "subject": subject,
                    "predicate": predicate,
                    "value": value,
                    "sources": [source],
                },
            )
            cursor = connection.execute(
                """
                INSERT INTO facts(subject, predicate, value, confidence, source, observed_at_ms,
                                  active, entry_id, supersedes_fact_id)
                VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (subject, predicate, value, confidence, source, observed, entry_id, previous_id),
            )
            fact_id = int(cursor.lastrowid)
            self._insert_fact_evidence(
                connection,
                fact_id=fact_id,
                claimed_value=value,
                source=source,
                evidence_kind=evidence_kind,
                raw_confidence=raw_confidence,
                effective_confidence=confidence,
                observed_at_ms=observed,
                decision="revised" if previous_id is not None else "created",
            )
            return fact_id

    def active_fact(self, subject: str, predicate: str) -> dict[str, object] | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT id, subject, predicate, value, confidence, source, observed_at_ms
                FROM facts WHERE subject=? AND predicate=? AND active=1
                ORDER BY id DESC LIMIT 1
                """,
                (subject, predicate),
            ).fetchone()
        return dict(row) if row else None

    def fact_history(self, subject: str, predicate: str) -> list[dict[str, object]]:
        """Return all revisions for a fact key, oldest first."""

        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, subject, predicate, value, confidence, source, observed_at_ms,
                       active, entry_id, supersedes_fact_id
                FROM facts WHERE subject=? AND predicate=? ORDER BY id
                """,
                (subject, predicate),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_fact_evidence(
        self,
        *,
        fact_id: int,
        claimed_value: str,
        source: str,
        evidence_kind: str,
        raw_confidence: float,
        effective_confidence: float,
        observed_at_ms: int | None = None,
        decision: str,
    ) -> int:
        """Attach provenance or a rejected contradiction without creating a false memory."""

        with self.connection(immediate=True) as connection:
            return self._insert_fact_evidence(
                connection,
                fact_id=int(fact_id),
                claimed_value=_required_text(claimed_value, "claimed_value", 2_000),
                source=_required_text(source, "source", 120),
                evidence_kind=_required_text(evidence_kind, "evidence_kind", 40),
                raw_confidence=_clamp(float(raw_confidence), 0.0, 1.0),
                effective_confidence=_clamp(float(effective_confidence), 0.0, 1.0),
                observed_at_ms=observed_at_ms or int(time.time() * 1000),
                decision=_required_text(decision, "decision", 40),
            )

    def fact_evidence(self, fact_id: int) -> list[dict[str, object]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, fact_id, claimed_value, source, evidence_kind, raw_confidence,
                       effective_confidence, observed_at_ms, decision
                FROM fact_evidence WHERE fact_id=? ORDER BY id
                """,
                (int(fact_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_lexical(self, query: str, limit: int = 20) -> list[tuple[MemoryEntry, float]]:
        safe_limit = max(1, min(int(limit), 100))
        fts_query = _build_fts_query(query)
        with self.connection() as connection:
            if fts_query:
                rows = connection.execute(
                    """
                    SELECT e.*, bm25(memory_fts, 2.0, 1.0) AS lexical_rank
                    FROM memory_fts
                    JOIN memory_entries e ON e.id=memory_fts.rowid
                    WHERE memory_fts MATCH ? AND e.active=1
                    ORDER BY lexical_rank LIMIT ?
                    """,
                    (fts_query, safe_limit),
                ).fetchall()
            else:
                needle = f"%{str(query or '').strip()[:200]}%"
                rows = connection.execute(
                    """
                    SELECT e.*, 0.0 AS lexical_rank FROM memory_entries e
                    WHERE e.active=1 AND (e.title LIKE ? OR e.body LIKE ?)
                    ORDER BY e.importance DESC, e.observed_at_ms DESC LIMIT ?
                    """,
                    (needle, needle, safe_limit),
                ).fetchall()
        return [(_row_to_entry(row), float(row["lexical_rank"])) for row in rows]

    def entries_with_embeddings(self) -> list[MemoryEntry]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memory_entries
                WHERE active=1 AND embedding IS NOT NULL AND embedding_dim > 0
                """
            ).fetchall()
        return [_row_to_entry(row) for row in rows]

    def _insert_entry(
        self,
        connection: sqlite3.Connection,
        *,
        kind: str,
        title: str,
        body: str,
        source: str,
        importance: float,
        observed_at_ms: int,
        embedding: Sequence[float] | None,
        metadata: dict[str, object] | None,
    ) -> int:
        vector = tuple(float(value) for value in (embedding or ()))
        blob = struct.pack(f"<{len(vector)}f", *vector) if vector else None
        cursor = connection.execute(
            """
            INSERT INTO memory_entries(kind, title, body, source, importance, observed_at_ms,
                                       active, embedding, embedding_dim, metadata_json)
            VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                kind,
                title,
                body,
                source,
                importance,
                int(observed_at_ms),
                blob,
                len(vector),
                json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        return int(cursor.lastrowid)

    def _insert_fact_evidence(
        self,
        connection: sqlite3.Connection,
        *,
        fact_id: int,
        claimed_value: str,
        source: str,
        evidence_kind: str,
        raw_confidence: float,
        effective_confidence: float,
        observed_at_ms: int,
        decision: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO fact_evidence(
                fact_id, claimed_value, source, evidence_kind, raw_confidence,
                effective_confidence, observed_at_ms, decision
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                claimed_value,
                source,
                evidence_kind,
                raw_confidence,
                effective_confidence,
                int(observed_at_ms),
                decision,
            ),
        )
        return int(cursor.lastrowid)

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(_SCHEMA)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source TEXT NOT NULL,
    importance REAL NOT NULL,
    observed_at_ms INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    embedding BLOB,
    embedding_dim INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memory_active_time ON memory_entries(active, observed_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_memory_kind_active ON memory_entries(kind, active);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    observed_at_ms INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    entry_id INTEGER NOT NULL REFERENCES memory_entries(id),
    supersedes_fact_id INTEGER REFERENCES facts(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_fact ON facts(subject, predicate) WHERE active=1;

CREATE TABLE IF NOT EXISTS fact_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id INTEGER NOT NULL REFERENCES facts(id),
    claimed_value TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    raw_confidence REAL NOT NULL,
    effective_confidence REAL NOT NULL,
    observed_at_ms INTEGER NOT NULL,
    decision TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_evidence_fact_time
ON fact_evidence(fact_id, observed_at_ms DESC);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(session_id, turn_id)
);
CREATE INDEX IF NOT EXISTS idx_turn_session_time ON turns(session_id, created_at_ms DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    title, body,
    content='memory_entries', content_rowid='id',
    tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS memory_entries_ai AFTER INSERT ON memory_entries BEGIN
  INSERT INTO memory_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS memory_entries_ad AFTER DELETE ON memory_entries BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body);
END;
CREATE TRIGGER IF NOT EXISTS memory_entries_au AFTER UPDATE OF title, body ON memory_entries BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body);
  INSERT INTO memory_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
"""


def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
    dimension = int(row["embedding_dim"] or 0)
    blob = row["embedding"]
    embedding = struct.unpack(f"<{dimension}f", blob) if blob and dimension else ()
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return MemoryEntry(
        id=int(row["id"]),
        kind=str(row["kind"]),
        title=str(row["title"]),
        body=str(row["body"]),
        source=str(row["source"]),
        importance=float(row["importance"]),
        observed_at_ms=int(row["observed_at_ms"]),
        embedding=tuple(float(value) for value in embedding),
        metadata=metadata,
    )


def _metadata_with_source(raw_metadata: str, source: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw_metadata or "{}")
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    metadata = parsed if isinstance(parsed, dict) else {}
    existing = metadata.get("sources", [])
    sources = [str(item) for item in existing] if isinstance(existing, list) else []
    if source not in sources:
        sources.append(source)
    # Full provenance remains in fact_evidence; keep prompt-facing metadata bounded.
    metadata["sources"] = sources[-16:]
    return metadata


def _build_fts_query(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip().lower())[:240]
    if len(text) < 3:
        return ""
    terms: list[str] = []
    for index in range(min(len(text) - 2, 48)):
        term = text[index : index + 3].replace('"', '""')
        if term not in terms:
            terms.append(term)
    return " OR ".join(f'"{term}"' for term in terms)


def _required_text(value: str, name: str, max_length: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized[:max_length]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
