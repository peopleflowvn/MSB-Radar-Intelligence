import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from radar_intelligence.contracts import DocumentRef
from radar_intelligence.indexing import (
    ChangeOperation,
    DocumentChange,
    FeedPage,
    InMemoryCursorStore,
    InMemoryDocumentIndex,
    IncrementalIndexer,
    IndexSyncCoordinator,
    SqliteCursorStore,
    SyncFailure,
)


def event(event_id, document_id, text="SQL"):
    return DocumentChange(
        event_id, ChangeOperation.UPSERT,
        DocumentRef(document_id, "p1", "1", "hash-" + document_id),
        datetime(2026, 9, 11, tzinfo=timezone.utc), "topcv", "cv", text,
    )


class ScriptedFeed:
    def __init__(self, pages):
        self.pages = list(pages)
        self.cursors = []

    def fetch(self, cursor=None):
        self.cursors.append(cursor)
        return self.pages.pop(0)


class FailingIndexer:
    def __init__(self, delegate, fail_event):
        self.delegate = delegate
        self.fail_event = fail_event

    def apply(self, change):
        if change.event_id == self.fail_event:
            raise RuntimeError("index failed")
        return self.delegate.apply(change)


class IndexSyncTest(unittest.TestCase):
    def test_commits_each_complete_page_and_reports_statuses(self):
        feed = ScriptedFeed([
            FeedPage((event("e1", "d1"),), "c1", True),
            FeedPage((event("e2", "d2"),), "c2", False),
        ])
        cursors = InMemoryCursorStore()
        store = InMemoryDocumentIndex()
        report = IndexSyncCoordinator(feed, IncrementalIndexer(store), cursors).run()
        self.assertEqual(feed.cursors, [None, "c1"])
        self.assertEqual((report.pages, report.events, report.indexed), (2, 2, 2))
        self.assertTrue(report.caught_up)
        self.assertEqual(report.end_cursor, "c2")

    def test_failed_event_does_not_advance_page_cursor(self):
        feed = ScriptedFeed([FeedPage((event("e1", "d1"), event("e2", "d2")), "c2", False)])
        cursors = InMemoryCursorStore("c0")
        delegate = IncrementalIndexer(InMemoryDocumentIndex())
        with self.assertRaises(SyncFailure) as caught:
            IndexSyncCoordinator(feed, FailingIndexer(delegate, "e2"), cursors).run()
        self.assertEqual(cursors.load(), "c0")
        self.assertEqual(caught.exception.event_id, "e2")
        self.assertEqual(caught.exception.document_id, "d2")
        self.assertEqual(caught.exception.cause_type, "RuntimeError")
        self.assertNotIn("SQL", str(caught.exception))

    def test_provider_failure_exposes_only_bounded_provider_status(self):
        from radar_intelligence.providers import ProviderError

        failure = SyncFailure(
            event_id="e1", document_id="d1", cursor=None,
            cause=ProviderError("GreenNode HTTP 400"),
        )
        self.assertIn("provider=GreenNode HTTP 400", str(failure))

    def test_retry_after_checkpoint_failure_is_safe(self):
        class FailingCursor(InMemoryCursorStore):
            def save(self, cursor):
                raise RuntimeError("checkpoint failed")

        store = InMemoryDocumentIndex()
        indexer = IncrementalIndexer(store)
        page = FeedPage((event("e1", "d1"),), "c1", False)
        with self.assertRaisesRegex(RuntimeError, "checkpoint failed"):
            IndexSyncCoordinator(ScriptedFeed([page]), indexer, FailingCursor()).run()
        good = InMemoryCursorStore()
        report = IndexSyncCoordinator(ScriptedFeed([page]), indexer, good).run()
        self.assertEqual(report.duplicate, 1)
        self.assertEqual(good.load(), "c1")

    def test_max_pages_stops_without_claiming_caught_up(self):
        report = IndexSyncCoordinator(
            ScriptedFeed([FeedPage((), "c1", True)]),
            IncrementalIndexer(InMemoryDocumentIndex()),
            InMemoryCursorStore(),
        ).run(max_pages=1)
        self.assertFalse(report.caught_up)

    def test_sqlite_cursor_is_durable_and_namespaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state" / "cursor.sqlite3"
            first = SqliteCursorStore(path, "feed-a")
            first.save("seq:12")
            self.assertEqual(SqliteCursorStore(path, "feed-a").load(), "seq:12")
            self.assertIsNone(SqliteCursorStore(path, "feed-b").load())


if __name__ == "__main__":
    unittest.main()
