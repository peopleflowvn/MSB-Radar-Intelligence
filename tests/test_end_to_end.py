import hashlib
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from radar_intelligence.contracts import DocumentRef, SearchRequest
from radar_intelligence.evidence import SourceSnapshot, resolve_citations
from radar_intelligence.indexing import (
    ChangeOperation, DocumentChange, DocumentConverter,
    InMemoryDocumentIndex, IncrementalIndexer,
)
from radar_intelligence.retrieval import (
    HybridRetriever, ProjectionError, RetrievalScope, project_search_documents,
)


class _Resolver:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def resolve(self, *, document_id, scope_token):
        self.last_scope = scope_token
        return self.snapshots.get(document_id)


def _change(event_id, document_id, person_id, text):
    digest = hashlib.sha256(text.encode()).hexdigest()
    return DocumentChange(
        event_id, ChangeOperation.UPSERT,
        DocumentRef(document_id, person_id, "v1", digest),
        datetime(2026, 1, 1, tzinfo=timezone.utc), "cv", "resume", text,
    )


class EndToEndTest(unittest.TestCase):
    def test_index_scope_retrieve_and_resolve_evidence(self):
        store = InMemoryDocumentIndex()
        indexer = IncrementalIndexer(store, DocumentConverter(max_chars=200))
        allowed = _change("e1", "d1", "p1", "Phan tich du lieu SQL ngan hang")
        forbidden = _change("e2", "d2", "p2", "Phan tich du lieu SQL bao mat")
        indexer.apply(allowed)
        indexer.apply(forbidden)

        records = project_search_documents(store.documents(), person_labels={"p1": "An", "p2": "Binh"})
        hits = HybridRetriever().search(
            SearchRequest("phan tich du lieu SQL", "opaque-scope", "u1"),
            records,
            RetrievalScope(frozenset({"p1"})),
        )
        self.assertEqual([hit.person.person_id for hit in hits], ["p1"])
        evidence = tuple(item for hit in hits for item in hit.evidence)
        resolver = _Resolver({
            "d1": SourceSnapshot("d1", "p1", "v1", allowed.document.content_hash),
        })
        validated = resolve_citations(
            evidence, (evidence[0].evidence_id,), allowed_person_ids={"p1"},
            scope_token="opaque-scope", resolver=resolver,
        )
        self.assertEqual(validated, (evidence[0],))
        self.assertEqual(resolver.last_scope, "opaque-scope")

    def test_projection_rejects_identity_metadata_drift(self):
        store = InMemoryDocumentIndex()
        change = _change("e1", "d1", "p1", "Python data")
        IncrementalIndexer(store).apply(change)
        document = store.documents()[0]
        damaged = replace(document, metadata={**document.metadata, "chunk_id": "different"})
        with self.assertRaisesRegex(ProjectionError, "does not match"):
            project_search_documents((damaged,))


if __name__ == "__main__":
    unittest.main()
