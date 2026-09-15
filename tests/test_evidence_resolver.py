import threading
import unittest

from radar_intelligence.contracts import Evidence
from radar_intelligence.evidence import EvidenceValidationError, SourceSnapshot, resolve_citations


def item():
    return Evidence("e1", "p1", "d1", "cv", "SQL", "page 1", 0.9, "hash-1", "v1")


def item_for(evidence_id, document_id, person_id="p1"):
    return Evidence(evidence_id, person_id, document_id, "cv", "SQL", "page 1", 0.9, "hash-1", "v1")


class FakeResolver:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []

    def resolve(self, *, document_id, scope_token):
        self.calls.append((document_id, scope_token))
        return self.snapshot


class EvidenceResolverTest(unittest.TestCase):
    def test_current_authorized_source_is_returned(self):
        resolver = FakeResolver(SourceSnapshot("d1", "p1", "v1", "hash-1"))
        result = resolve_citations((item(),), ("e1",), allowed_person_ids={"p1"}, scope_token="scope", resolver=resolver)
        self.assertEqual(result, (item(),))
        self.assertEqual(resolver.calls, [("d1", "scope")])

    def test_missing_source_fails_closed(self):
        with self.assertRaisesRegex(EvidenceValidationError, "unavailable or unauthorized"):
            resolve_citations((item(),), ("e1",), allowed_person_ids={"p1"}, scope_token="scope", resolver=FakeResolver(None))

    def test_version_or_hash_drift_is_stale(self):
        resolver = FakeResolver(SourceSnapshot("d1", "p1", "v2", "hash-2"))
        with self.assertRaisesRegex(EvidenceValidationError, "stale evidence"):
            resolve_citations((item(),), ("e1",), allowed_person_ids={"p1"}, scope_token="scope", resolver=resolver)

    def test_person_reassignment_is_identity_mismatch(self):
        resolver = FakeResolver(SourceSnapshot("d1", "p2", "v1", "hash-1"))
        with self.assertRaisesRegex(EvidenceValidationError, "identity mismatch"):
            resolve_citations((item(),), ("e1",), allowed_person_ids={"p1"}, scope_token="scope", resolver=resolver)

    def test_empty_scope_never_calls_resolver(self):
        resolver = FakeResolver(SourceSnapshot("d1", "p1", "v1", "hash-1"))
        with self.assertRaisesRegex(EvidenceValidationError, "scope_token"):
            resolve_citations((item(),), ("e1",), allowed_person_ids={"p1"}, scope_token="", resolver=resolver)
        self.assertEqual(resolver.calls, [])

    def test_multiple_documents_are_resolved_concurrently(self):
        class ConcurrentResolver:
            def __init__(self):
                self.seen_concurrently = threading.Event()
                self.barrier = threading.Barrier(3, timeout=5)

            def resolve(self, *, document_id, scope_token):
                self.barrier.wait()  # only passes if all 3 calls overlap in time
                return SourceSnapshot(document_id, "p1", "v1", "hash-1")

        evidence = tuple(item_for(f"e{i}", f"d{i}") for i in range(3))
        cited_ids = tuple(row.evidence_id for row in evidence)
        resolver = ConcurrentResolver()
        result = resolve_citations(
            evidence, cited_ids, allowed_person_ids={"p1"}, scope_token="scope", resolver=resolver)
        self.assertEqual({item.evidence_id for item in result}, set(cited_ids))

    def test_multiple_documents_preserve_first_seen_order_on_failure(self):
        class OrderedFailingResolver:
            def __init__(self):
                self.calls = []

            def resolve(self, *, document_id, scope_token):
                self.calls.append(document_id)
                if document_id == "d1":
                    return None
                return SourceSnapshot(document_id, "p1", "v1", "hash-1")

        evidence = (item_for("e1", "d1"), item_for("e2", "d2"))
        resolver = OrderedFailingResolver()
        with self.assertRaisesRegex(EvidenceValidationError, "unavailable or unauthorized: e1"):
            resolve_citations(
                evidence, ("e1", "e2"), allowed_person_ids={"p1"},
                scope_token="scope", resolver=resolver)


if __name__ == "__main__":
    unittest.main()
