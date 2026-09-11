import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar_intelligence.contracts import DocumentRef
from radar_intelligence.indexing import (
    ChangeOperation, DocumentChange, DocumentConverter, IncrementalIndexer,
    SqliteDocumentIndex,
)


NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def change(event_id, *, operation=ChangeOperation.UPSERT, updated_at=NOW, text="Python SQL"):
    return DocumentChange(
        event_id=event_id, operation=operation,
        document=DocumentRef("doc-1", "person-1", "v1", "hash-1", "source-1"),
        updated_at=updated_at, source="topcv", document_type="cv", text=text,
    )


class SqliteDocumentIndexTest(unittest.TestCase):
    def test_chunks_and_lifecycle_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite3"
            first = IncrementalIndexer(SqliteDocumentIndex(path), DocumentConverter(100))
            self.assertEqual(first.apply(change("event-1")).status, "indexed")

            reopened = SqliteDocumentIndex(path)
            self.assertEqual(reopened.documents("doc-1")[0].content, "Python SQL")
            second = IncrementalIndexer(reopened, DocumentConverter(100))
            self.assertEqual(second.apply(change("event-1")).status, "duplicate")
            self.assertEqual(second.apply(change(
                "event-2", operation=ChangeOperation.DELETE,
                updated_at=NOW + timedelta(seconds=1), text=None)).status, "deleted")

            final = SqliteDocumentIndex(path)
            self.assertEqual(final.documents("doc-1"), ())
            self.assertEqual(final.statistics(), {
                "events": 2, "documents": 0, "deleted": 1, "chunks": 0,
            })
            self.assertEqual(IncrementalIndexer(final).apply(change("late")).status, "stale")

    def test_reused_event_id_with_changed_payload_fails_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite3"
            IncrementalIndexer(SqliteDocumentIndex(path)).apply(change("same"))
            with self.assertRaises(ValueError):
                IncrementalIndexer(SqliteDocumentIndex(path)).apply(change(
                    "same", updated_at=NOW + timedelta(seconds=1)))


if __name__ == "__main__":
    unittest.main()
