from __future__ import annotations

from contextlib import closing
from datetime import timezone
import json
from pathlib import Path
import sqlite3

from .core import ChangeOperation, DocumentChange, IndexApplyResult, SearchDocument


class SqliteDocumentIndex:
    """Durable document lifecycle and chunks in one atomic SQLite transaction."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS index_event (
                    event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS document_marker (
                    document_id TEXT PRIMARY KEY, ordering_key TEXT NOT NULL,
                    operation TEXT NOT NULL, event_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS search_chunk (
                    chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
                    content TEXT NOT NULL, embedding TEXT, metadata TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS ix_search_chunk_document
                    ON search_chunk(document_id);
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    @staticmethod
    def _ordering_key(change: DocumentChange) -> str:
        priority = 1 if change.operation == ChangeOperation.DELETE else 0
        stamp = change.updated_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
        return f"{stamp}\x1f{priority}\x1f{change.event_id}"

    def apply(self, change: DocumentChange, chunks: tuple[SearchDocument, ...]) -> IndexApplyResult:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            event = connection.execute(
                "SELECT fingerprint FROM index_event WHERE event_id=?", (change.event_id,)
            ).fetchone()
            if event is not None:
                if event[0] != change.fingerprint:
                    raise ValueError("event_id was reused with a different payload")
                count = self._count(connection, change.document.document_id)
                return IndexApplyResult("duplicate", change.document.document_id, count)

            incoming = self._ordering_key(change)
            marker = connection.execute(
                "SELECT ordering_key FROM document_marker WHERE document_id=?",
                (change.document.document_id,),
            ).fetchone()
            connection.execute(
                "INSERT INTO index_event(event_id, fingerprint) VALUES(?, ?)",
                (change.event_id, change.fingerprint),
            )
            if marker is not None and incoming <= marker[0]:
                return IndexApplyResult(
                    "stale", change.document.document_id,
                    self._count(connection, change.document.document_id))

            connection.execute(
                "INSERT INTO document_marker(document_id, ordering_key, operation, event_id) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(document_id) DO UPDATE SET "
                "ordering_key=excluded.ordering_key, operation=excluded.operation, event_id=excluded.event_id",
                (change.document.document_id, incoming, change.operation.value, change.event_id),
            )
            connection.execute(
                "DELETE FROM search_chunk WHERE document_id=?", (change.document.document_id,))
            if change.operation == ChangeOperation.DELETE:
                return IndexApplyResult("deleted", change.document.document_id, 0)
            connection.executemany(
                "INSERT INTO search_chunk(chunk_id, document_id, content, embedding, metadata) "
                "VALUES(?, ?, ?, ?, ?)",
                [(chunk.chunk_id, change.document.document_id, chunk.content,
                  json.dumps(chunk.embedding) if chunk.embedding is not None else None,
                  json.dumps(dict(chunk.metadata), separators=(",", ":"), ensure_ascii=False))
                 for chunk in chunks],
            )
            return IndexApplyResult("indexed", change.document.document_id, len(chunks))

    @staticmethod
    def _count(connection: sqlite3.Connection, document_id: str) -> int:
        return int(connection.execute(
            "SELECT COUNT(*) FROM search_chunk WHERE document_id=?", (document_id,)
        ).fetchone()[0])

    def documents(self, document_id: str | None = None) -> tuple[SearchDocument, ...]:
        query = "SELECT chunk_id, content, embedding, metadata FROM search_chunk"
        params: tuple[str, ...] = ()
        if document_id is not None:
            query += " WHERE document_id=?"
            params = (document_id,)
        query += " ORDER BY chunk_id"
        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(SearchDocument(
            chunk_id=row[0], content=row[1],
            embedding=tuple(json.loads(row[2])) if row[2] is not None else None,
            metadata=json.loads(row[3]),
        ) for row in rows)

    def statistics(self) -> dict[str, int]:
        """Return non-sensitive lifecycle counts for production observability."""
        with closing(self._connect()) as connection:
            events = int(connection.execute("SELECT COUNT(*) FROM index_event").fetchone()[0])
            documents = int(connection.execute(
                "SELECT COUNT(*) FROM document_marker WHERE operation != 'delete'").fetchone()[0])
            deleted = int(connection.execute(
                "SELECT COUNT(*) FROM document_marker WHERE operation = 'delete'").fetchone()[0])
            chunks = int(connection.execute("SELECT COUNT(*) FROM search_chunk").fetchone()[0])
        return {"events": events, "documents": documents, "deleted": deleted, "chunks": chunks}
