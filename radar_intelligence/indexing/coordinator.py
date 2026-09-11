from __future__ import annotations

from dataclasses import dataclass
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
        cursor = start
        counts = {"indexed": 0, "deleted": 0, "duplicate": 0, "stale": 0}
        pages = events = chunks = 0
        caught_up = False
        while pages < max_pages:
            page = self._feed.fetch(cursor)
            if page.events and not page.next_cursor:
                raise ValueError("non-empty feed page must advance the cursor")
            for event in page.events:
                result = self._indexer.apply(event)
                if result.status not in counts:
                    raise ValueError(f"unknown index status: {result.status}")
                counts[result.status] += 1
                events += 1
                chunks += result.chunk_count if result.status == "indexed" else 0
            # Save only after every event in this page has been applied.
            if page.next_cursor is not None:
                self._cursors.save(page.next_cursor)
                cursor = page.next_cursor
            pages += 1
            if not page.has_more:
                caught_up = True
                break
        return SyncReport(start, cursor, pages, events, chunks=chunks, caught_up=caught_up, **counts)
