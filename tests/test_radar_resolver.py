import json
import unittest

from radar_intelligence.evidence import EvidenceValidationError, RadarHttpSourceResolver, RadarResolverConfig


class FakeClient:
    def __init__(self, status, payload=b""):
        self.status = status
        self.payload = payload
        self.call = None

    def get(self, url, headers, timeout_seconds):
        self.call = (url, headers, timeout_seconds)
        return self.status, self.payload


class RadarResolverTest(unittest.TestCase):
    def config(self):
        return RadarResolverConfig("https://radar.example", "service-secret", 4)

    def test_resolves_stable_snapshot_with_separate_scope_header(self):
        client = FakeClient(200, json.dumps({
            "document_id": 12, "person_id": 7, "version": "text:31",
            "content_hash": "abc", "exists": True,
        }).encode())
        snapshot = RadarHttpSourceResolver(self.config(), client).resolve(document_id="12", scope_token="opaque-scope")
        self.assertEqual((snapshot.document_id, snapshot.person_id), ("12", "7"))
        url, headers, timeout = client.call
        self.assertEqual(url, "https://radar.example/api/v1/talent/intelligence/evidence/documents/12/")
        self.assertEqual(headers["X-Radar-Scope-Token"], "opaque-scope")
        self.assertEqual(headers["Authorization"], "Bearer service-secret")
        self.assertEqual(timeout, 4)

    def test_forbidden_and_missing_are_indistinguishable(self):
        for status in (403, 404):
            self.assertIsNone(RadarHttpSourceResolver(self.config(), FakeClient(status)).resolve(
                document_id="12", scope_token="scope"
            ))

    def test_deleted_source_is_explicit(self):
        snapshot = RadarHttpSourceResolver(self.config(), FakeClient(410)).resolve(document_id="12", scope_token="scope")
        self.assertFalse(snapshot.exists)

    def test_malformed_or_error_response_fails_closed(self):
        with self.assertRaisesRegex(EvidenceValidationError, "malformed"):
            RadarHttpSourceResolver(self.config(), FakeClient(200, b"{}" )).resolve(document_id="12", scope_token="scope")
        with self.assertRaisesRegex(EvidenceValidationError, "HTTP 500"):
            RadarHttpSourceResolver(self.config(), FakeClient(500)).resolve(document_id="12", scope_token="scope")

    def test_configuration_requires_https(self):
        with self.assertRaises(ValueError):
            RadarResolverConfig("http://radar.example", "secret")


if __name__ == "__main__":
    unittest.main()
