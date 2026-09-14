from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import time
from typing import Protocol

from .core import IncrementalIndexer
from .radar_feed import FeedPage


class FeedClient(Protocol):
    def fetch(self, cursor: str | None = None) -> FeedPage: ...


class CursorStore(Protocol):
    def load(self) -> str | None: ...
    def save(self, cursor: str) -> None: ...


class InMemoryCursorStore:
    def __init__(self, cursor: str | None = None) -> None:
        self._cursor = cursor

    def load(self) -> str | None:
        return self._cursor

    def save(self, cursor: str) -> None:
        if not cursor.strip():
            raise ValueError("cursor must not be empty")
        self._cursor = cursor


class SqliteCursorStore:
    """Durable namespaced checkpoint store using an atomic SQLite upsert."""

    def __init__(self, path: str | Path, namespace: str = "radar-document-feed") -> None:
        self._path = Path(path)
        self._namespace = namespace.strip()
        if not self._namespace:
            raise ValueError("cursor namespace must not be empty")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS sync_cursor ("
                    "namespace TEXT PRIMARY KEY, cursor TEXT NOT NULL, updated_at TEXT NOT NULL)"
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    def load(self) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT cursor FROM sync_cursor WHERE namespace = ?", (self._namespace,)
            ).fetchone()
        return None if row is None else str(row[0])

    def save(self, cursor: str) -> None:
        cursor = cursor.strip()
        if not cursor:
            raise ValueError("cursor must not be empty")
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO sync_cursor(namespace, cursor, updated_at) VALUES(?, ?, ?) "
                    "ON CONFLICT(namespace) DO UPDATE SET cursor=excluded.cursor, updated_at=excluded.updated_at",
                    (self._namespace, cursor, datetime.now(timezone.utc).isoformat()),
                )


class SyncFailure(RuntimeError):
    def __init__(self, *, event_id: str, document_id: str, cursor: str | None, cause: Exception) -> None:
        self.event_id = event_id
        self.document_id = document_id
        self.cursor = cursor
        self.cause_type = type(cause).__name__
        safe_provider_detail = str(cause) if (
            self.cause_type == "ProviderError" and str(cause).startswith("GreenNode ")
        ) else ""
        super().__init__(
            f"index event failed: event_id={event_id} document_id={document_id} "
            f"cursor={cursor or '<start>'} cause={self.cause_type}"
            + (f" provider={safe_provider_detail}" if safe_provider_detail else "")
        )


@dataclass(frozen=True)
class SyncReport:
    start_cursor: str | None
    end_cursor: str | None
    pages: int
    events: int
    indexed: int
    deleted: int
    duplicate: int
    stale: int
    chunks: int
    caught_up: bool
    duration_ms: float


class IndexSyncCoordinator:
    """Apply complete feed pages before committing their durable cursor."""

    def __init__(self, feed: FeedClient, indexer: IncrementalIndexer, cursors: CursorStore) -> None:
        self._feed = feed
        self._indexer = indexer
        self._cursors = cursors

    def run(self, max_pages: int = 100) -> SyncReport:
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        start = self._cursors.load()
        started = time.perf_counter()
        cursor = start
        counts = {"indexed": 0, "deleted": 0, "duplicate": 0, "stale": 0}
        pages = events = chunks = 0
        caught_up = False
        while pages < max_pages:
            page = self._feed.fetch(cursor)
            if page.events and not page.next_cursor:
                raise ValueError("non-empty feed page must advance the cursor")
            for event in page.events:
                try:
                    result = self._indexer.apply(event)
                except Exception as exc:
                    raise SyncFailure(
                        event_id=event.event_id,
                        document_id=event.document.document_id,
                        cursor=cursor,
                        cause=exc,
                    ) from exc
                if result.status not in counts:
                    raise ValueError(f"unknown index status: {result.status}")
                counts[result.status] += 1
                events += 1
                chunks += result.chunk_count if result.status == "indexed" else 0
            # Save only after every event in this page has been applied.
            if page.next_cursor is not None and page.next_cursor != cursor:
                self._cursors.save(page.next_cursor)
            if page.next_cursor is not None:
                cursor = page.next_cursor
            pages += 1
            if not page.has_more:
                caught_up = True
                break
        return SyncReport(
            start, cursor, pages, events, chunks=chunks, caught_up=caught_up,
            duration_ms=round((time.perf_counter() - started) * 1000, 3), **counts,
        )
