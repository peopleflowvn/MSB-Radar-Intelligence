import json
import unittest

from radar_intelligence.auth import RadarScopeConfig, RadarScopeValidator, ScopeValidationError


class FakeClient:
    def __init__(self, status, body):
        self.status, self.body, self.call = status, body, None

    def post(self, url, headers, timeout_seconds):
        self.call = (url, headers, timeout_seconds)
        return self.status, self.body


class ScopeValidatorTest(unittest.TestCase):
    def config(self):
        return RadarScopeConfig("https://radar.example", "service", 4)

    def test_current_radar_scope_is_required_and_validated_server_side(self):
        client = FakeClient(200, json.dumps(
            {"allowed": True, "scope": "all_applicants"}).encode())
        self.assertTrue(RadarScopeValidator(self.config(), client).validate("signed-scope"))
        url, headers, timeout = client.call
        self.assertEqual(url, "https://radar.example/api/v1/talent/intelligence/scope/validate/")
        self.assertEqual(headers["Authorization"], "Bearer service")
        self.assertEqual(headers["X-Radar-Scope-Token"], "signed-scope")
        self.assertEqual(timeout, 4)

    def test_denied_or_unexpected_claim_fails_closed(self):
        self.assertFalse(RadarScopeValidator(
            self.config(), FakeClient(404, b"{}")).validate("scope"))
        self.assertFalse(RadarScopeValidator(self.config(), FakeClient(
            200, b'{"allowed":true,"scope":"too_broad"}')).validate("scope"))

    def test_internal_hub_sets_django_host_header(self):
        client = FakeClient(200, b'{"allowed":true,"scope":"all_applicants"}')
        config = RadarScopeConfig("http://hub:8000", "service")
        self.assertTrue(RadarScopeValidator(config, client).validate("scope"))
        self.assertEqual(client.call[1]["Host"], "localhost")

    def test_service_failure_is_visible(self):
        with self.assertRaisesRegex(ScopeValidationError, "HTTP 500"):
            RadarScopeValidator(self.config(), FakeClient(500, b"{}")).validate("scope")

    def test_additive_response_fields_do_not_break_a_valid_claim(self):
        client = FakeClient(200, json.dumps({
            "allowed": True, "scope": "all_applicants", "request_id": "trace-1",
        }).encode())
        self.assertTrue(RadarScopeValidator(self.config(), client).validate("scope"))

    def test_non_object_payload_fails_closed(self):
        client = FakeClient(200, b"[true]")
        self.assertFalse(RadarScopeValidator(self.config(), client).validate("scope"))
