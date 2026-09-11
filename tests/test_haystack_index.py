from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ["HAYSTACK_TELEMETRY_ENABLED"] = "false"

try:
    from haystack.document_stores.in_memory import InMemoryDocumentStore
except ImportError:  # pragma: no cover - optional dependency environment
    InMemoryDocumentStore = None

from radar_intelligence.contracts import DocumentRef
from radar_intelligence.indexing import (
    ChangeOperation,
    DocumentChange,
    HaystackDocumentIndex,
    IncrementalIndexer,
)


NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def change(event_id, *, operation=ChangeOperation.UPSERT, person_id="p1", version="1", at=NOW, text="SQL\nPython"):
    return DocumentChange(
        event_id=event_id,
        operation=operation,
        document=DocumentRef("d1", person_id, version, f"sha-{version}", "sr1"),
        updated_at=at,
        source="topcv",
        document_type="cv",
        text=text,
    )


@unittest.skipIf(InMemoryDocumentStore is None, "Haystack optional dependency is not installed")
class HaystackIndexTest(unittest.TestCase):
    def setUp(self):
        haystack_store = InMemoryDocumentStore(shared=False)
        self.store = HaystackDocumentIndex(haystack_store)
        self.indexer = IncrementalIndexer(self.store)

    def test_real_haystack_store_preserves_mapping_and_replay(self):
        first = self.indexer.apply(change("e1"))
        replay = self.indexer.apply(change("e1"))
        documents = self.store.documents("d1")
        self.assertEqual(first.status, "indexed")
        self.assertEqual(replay.status, "duplicate")
        self.assertTrue(documents)
        self.assertTrue(all(document.metadata["person_id"] == "p1" for document in documents))

    def test_new_version_replaces_old_chunks(self):
        self.indexer.apply(change("e1"))
        self.indexer.apply(change("e2", version="2", at=NOW + timedelta(minutes=1), text="Risk management"))
        documents = self.store.documents("d1")
        self.assertTrue(documents)
        self.assertTrue(all(document.metadata["version"] == "2" for document in documents))

    def test_delete_and_person_reassignment(self):
        self.indexer.apply(change("e1"))
        self.indexer.apply(change("e2", person_id="p2", operation=ChangeOperation.PERSON_REASSIGNED, at=NOW + timedelta(minutes=1)))
        self.assertTrue(all(document.metadata["person_id"] == "p2" for document in self.store.documents("d1")))
        deleted = self.indexer.apply(change("e3", operation=ChangeOperation.DELETE, at=NOW + timedelta(minutes=2), text=None))
        self.assertEqual(deleted.status, "deleted")
        self.assertEqual(self.store.documents("d1"), ())


if __name__ == "__main__":
    unittest.main()
