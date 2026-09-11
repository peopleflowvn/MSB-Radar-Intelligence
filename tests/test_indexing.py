from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from radar_intelligence.contracts import DocumentRef
from radar_intelligence.indexing import (
    ChangeOperation,
    DocumentChange,
    DocumentConverter,
    InMemoryDocumentIndex,
    IncrementalIndexer,
)


NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def change(
    event_id: str,
    operation: ChangeOperation = ChangeOperation.UPSERT,
    *,
    person_id: str = "p1",
    updated_at: datetime = NOW,
    text: str | None = "SQL at Bank A\nLed five analysts",
) -> DocumentChange:
    return DocumentChange(
        event_id=event_id,
        operation=operation,
        document=DocumentRef("d1", person_id, "1", "sha-1", "sr1"),
        updated_at=updated_at,
        source="topcv",
        document_type="cv",
        text=text,
    )


class FakeEmbedder:
    def embed_documents(self, texts):
        return [[float(len(text)), 1.0] for text in texts]


class IndexingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryDocumentIndex()
        self.indexer = IncrementalIndexer(self.store, DocumentConverter(100), FakeEmbedder())

    def test_chunks_keep_required_radar_mapping(self) -> None:
        result = self.indexer.apply(change("e1"))
        chunks = self.store.documents("d1")
        self.assertEqual(result.status, "indexed")
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(item.metadata["person_id"] == "p1" for item in chunks))
        self.assertTrue(all(item.metadata["document_id"] == "d1" for item in chunks))
        self.assertTrue(all(item.embedding for item in chunks))

    def test_replayed_event_is_idempotent(self) -> None:
        first = self.indexer.apply(change("e1"))
        second = self.indexer.apply(change("e1"))
        self.assertEqual(first.chunk_count, second.chunk_count)
        self.assertEqual(second.status, "duplicate")

    def test_event_id_cannot_hide_a_different_payload(self) -> None:
        self.indexer.apply(change("e1"))
        with self.assertRaises(ValueError):
            self.indexer.apply(change("e1", person_id="p2"))

    def test_delete_blocks_older_upsert(self) -> None:
        self.indexer.apply(change("e1"))
        deletion = change("e2", ChangeOperation.DELETE, updated_at=NOW + timedelta(minutes=2), text=None)
        self.assertEqual(self.indexer.apply(deletion).status, "deleted")
        stale = change("e3", updated_at=NOW + timedelta(minutes=1))
        self.assertEqual(self.indexer.apply(stale).status, "stale")
        self.assertEqual(self.store.documents("d1"), ())

    def test_person_reassignment_replaces_all_chunks(self) -> None:
        self.indexer.apply(change("e1"))
        moved = change(
            "e2",
            ChangeOperation.PERSON_REASSIGNED,
            person_id="p2",
            updated_at=NOW + timedelta(minutes=1),
        )
        self.indexer.apply(moved)
        self.assertTrue(all(item.metadata["person_id"] == "p2" for item in self.store.documents("d1")))

    def test_embedding_batch_must_match_chunks(self) -> None:
        class BadEmbedder:
            def embed_documents(self, texts):
                return []

        bad = IncrementalIndexer(self.store, embedder=BadEmbedder())
        with self.assertRaises(ValueError):
            bad.apply(change("bad"))


if __name__ == "__main__":
    unittest.main()
