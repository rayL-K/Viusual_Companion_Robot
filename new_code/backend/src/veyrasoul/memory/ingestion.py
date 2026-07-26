"""Safe, idempotent document ingestion for retrieval-augmented generation."""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass

from .embedding import EmbeddingProvider, validate_embeddings
from .namespace import MemoryNamespace, assert_bound_store
from .store import MemoryStore


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    document_id: str
    content_hash: str
    chunk_ids: tuple[str, ...]
    unchanged: bool = False


class DocumentIngestor:
    MAX_DOCUMENT_CHARS = 2_000_000

    def __init__(
        self,
        store: MemoryStore,
        namespace: MemoryNamespace,
        embeddings: EmbeddingProvider,
        *,
        chunk_chars: int = 900,
        overlap_chars: int = 120,
    ) -> None:
        if not 200 <= chunk_chars <= 12_000:
            raise ValueError("chunk_chars must be between 200 and 12000")
        if not 0 <= overlap_chars < chunk_chars // 2:
            raise ValueError("overlap_chars must be less than half of chunk_chars")
        self.store = store
        self.namespace = namespace
        self.embeddings = embeddings
        self.chunk_chars = chunk_chars
        self.overlap_chars = overlap_chars
        assert_bound_store(store, namespace)
        self._initialize()

    def ingest(
        self,
        *,
        document_id: str,
        title: str,
        text: str,
        source: str,
        metadata: dict[str, object] | None = None,
    ) -> IngestedDocument:
        stable_document_id = _identifier(document_id, "document_id")
        clean_title = _clean_text(title, "title", 240)
        clean_source = _clean_text(source, "source", 120)
        clean_text = _safe_document_text(text, self.MAX_DOCUMENT_CHARS)
        content_hash = _digest(clean_text)
        safe_metadata = _safe_metadata(metadata)
        revision_hash = _digest(
            json.dumps(
                {
                    "content_hash": content_hash,
                    "title": clean_title,
                    "source": clean_source,
                    "metadata": safe_metadata,
                    "embedding_model": self.embeddings.model_id,
                    "embedding_dimension": self.embeddings.dimension,
                    "chunk_chars": self.chunk_chars,
                    "overlap_chars": self.overlap_chars,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        chunks = _chunk_text(clean_text, self.chunk_chars, self.overlap_chars)
        chunk_ids = tuple(
            _digest(f"{stable_document_id}\0{index}\0{chunk}")[:32]
            for index, chunk in enumerate(chunks)
        )

        with self.store.connection() as connection:
            existing = connection.execute(
                """
                SELECT revision_hash FROM rag_documents
                WHERE document_id=? AND active=1
                """,
                (stable_document_id,),
            ).fetchone()
        if existing and str(existing["revision_hash"] or "") == revision_hash:
            return IngestedDocument(stable_document_id, content_hash, chunk_ids, True)

        vectors = validate_embeddings(
            self.embeddings.embed_documents(chunks), len(chunks), self.embeddings.dimension
        )
        safe_metadata.update(
            {
                "namespace": self.namespace.key,
                "document_id": stable_document_id,
                "trusted": False,
                "instructions_allowed": False,
                "embedding_model": self.embeddings.model_id,
            }
        )
        with self.store.connection(immediate=True) as connection:
            old_rows = connection.execute(
                "SELECT entry_id FROM rag_chunks WHERE document_id=? AND active=1",
                (stable_document_id,),
            ).fetchall()
            if old_rows:
                connection.execute(
                    "DELETE FROM rag_chunks WHERE document_id=?",
                    (stable_document_id,),
                )
                connection.execute(
                    "DELETE FROM rag_documents WHERE document_id=?",
                    (stable_document_id,),
                )
                connection.executemany(
                    "DELETE FROM memory_entries WHERE id=?",
                    [(int(row["entry_id"]),) for row in old_rows],
                )
            connection.execute(
                """
                INSERT INTO rag_documents(
                    document_id, title, source, content_hash, revision_hash,
                    metadata_json, namespace_key, active
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    stable_document_id,
                    clean_title,
                    clean_source,
                    content_hash,
                    revision_hash,
                    json.dumps(safe_metadata, ensure_ascii=False, separators=(",", ":")),
                    self.namespace.key,
                ),
            )
            for index, (chunk, chunk_id, vector) in enumerate(zip(chunks, chunk_ids, vectors)):
                entry_metadata = dict(safe_metadata)
                entry_metadata.update({"chunk_id": chunk_id, "chunk_index": index})
                entry_id = self.store._insert_entry(
                    connection,
                    kind="document",
                    title=clean_title,
                    body=chunk,
                    source=clean_source,
                    importance=0.55,
                    observed_at_ms=int(time.time() * 1000),
                    embedding=vector,
                    metadata=entry_metadata,
                )
                connection.execute(
                    """
                    INSERT INTO rag_chunks(
                        chunk_id, document_id, entry_id, chunk_index, active
                    ) VALUES(?, ?, ?, ?, 1)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        document_id=excluded.document_id,
                        entry_id=excluded.entry_id,
                        chunk_index=excluded.chunk_index,
                        active=1
                    """,
                    (chunk_id, stable_document_id, entry_id, index),
                )
        return IngestedDocument(stable_document_id, content_hash, chunk_ids)

    def delete(self, document_id: str) -> bool:
        stable_document_id = _identifier(document_id, "document_id")
        with self.store.connection(immediate=True) as connection:
            rows = connection.execute(
                "SELECT entry_id FROM rag_chunks WHERE document_id=? AND active=1",
                (stable_document_id,),
            ).fetchall()
            connection.execute(
                "DELETE FROM rag_chunks WHERE document_id=?",
                (stable_document_id,),
            )
            connection.execute(
                "DELETE FROM rag_documents WHERE document_id=?",
                (stable_document_id,),
            )
            connection.executemany(
                "DELETE FROM memory_entries WHERE id=?",
                [(int(row["entry_id"]),) for row in rows],
            )
            return bool(rows)

    def _initialize(self) -> None:
        with self.store.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    revision_hash TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    namespace_key TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_one_active_document
                ON rag_documents(document_id) WHERE active=1;
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    entry_id INTEGER NOT NULL REFERENCES memory_entries(id),
                    chunk_index INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_rag_chunks_document
                ON rag_chunks(document_id, active);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(rag_documents)").fetchall()
            }
            if "revision_hash" not in columns:
                connection.execute("ALTER TABLE rag_documents ADD COLUMN revision_hash TEXT")
            if "metadata_json" not in columns:
                connection.execute(
                    "ALTER TABLE rag_documents ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                )


def _safe_document_text(value: str, max_chars: int) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).replace("\r\n", "\n")
    if "\x00" in text:
        raise ValueError("document contains binary NUL bytes")
    forbidden = sum(
        1 for char in text if unicodedata.category(char) == "Cc" and char not in "\n\t"
    )
    if forbidden:
        raise ValueError("document contains unsafe control characters")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    if not text:
        raise ValueError("document text must not be empty")
    if len(text) > max_chars:
        raise ValueError("document exceeds the ingestion size limit")
    return text


def _chunk_text(text: str, target: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    cursor = 0
    while cursor < len(text):
        end = min(len(text), cursor + target)
        if end < len(text):
            boundary = max(
                text.rfind("\n", cursor + target // 2, end),
                text.rfind("。", cursor + target // 2, end),
                text.rfind(".", cursor + target // 2, end),
            )
            if boundary > cursor:
                end = boundary + 1
        chunk = text[cursor:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        cursor = max(cursor + 1, end - overlap)
    return chunks


def _safe_metadata(metadata: dict[str, object] | None) -> dict[str, object]:
    raw = dict(metadata or {})
    for reserved in ("namespace", "document_id", "trusted", "instructions_allowed"):
        raw.pop(reserved, None)
    encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > 8_000:
        raise ValueError("document metadata is too large")
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError("document metadata must be an object")
    return decoded


def _identifier(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", normalized):
        raise ValueError(f"{name} is invalid")
    return normalized


def _clean_text(value: str, name: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    if len(normalized) > limit:
        raise ValueError(f"{name} exceeds the {limit} character limit")
    return normalized


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
