import unittest

from radar_intelligence.contracts import Evidence
from radar_intelligence.evidence import EvidenceValidationError, SourceSnapshot, resolve_citations


def item():
    return Evidence("e1", "p1", "d1", "cv", "SQL", "page 1", 0.9, "hash-1", "v1")


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


if __name__ == "__main__":
    unittest.main()
