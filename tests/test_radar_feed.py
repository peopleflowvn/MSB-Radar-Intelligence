import json
import unittest

from radar_intelligence.indexing import ChangeOperation, FeedError, RadarDocumentFeedClient, RadarFeedConfig


class FakeClient:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload
        self.call = None

    def get(self, url, headers, timeout_seconds):
        self.call = (url, headers, timeout_seconds)
        return self.status, self.payload


def event(operation="upsert", text="SQL", event_id="evt-1"):
    return {
        "event_id": event_id, "operation": operation, "document_id": 12,
        "person_id": 7, "version": "text:31", "content_hash": "hash-31",
        "source_record_id": 5, "source": "topcv", "document_type": "cv",
        "updated_at": "2026-09-11T10:00:00Z", "document_date": "2026-09-01T00:00:00Z",
        "application_id": 9, "text": text,
    }


class RadarFeedTest(unittest.TestCase):
    def config(self):
        return RadarFeedConfig("https://radar.example", "service", "index-scope", page_size=50)

    def test_fetches_ordered_page_and_maps_contract(self):
        client = FakeClient(200, json.dumps({
            "events": [event()], "next_cursor": "seq:101", "has_more": True,
        }).encode())
        page = RadarDocumentFeedClient(self.config(), client).fetch("seq:100")
        self.assertEqual(page.events[0].operation, ChangeOperation.UPSERT)
        self.assertEqual(page.events[0].document.person_id, "7")
        self.assertEqual(page.events[0].document.content_hash, "hash-31")
        self.assertIn("cursor=seq%3A100", client.call[0])
        self.assertEqual(client.call[1]["X-Radar-Scope-Token"], "index-scope")

    def test_delete_event_does_not_require_text(self):
        row = event("delete", None)
        page = RadarDocumentFeedClient(self.config(), FakeClient(200, json.dumps({
            "events": [row], "next_cursor": "seq:1", "has_more": False,
        }).encode())).fetch()
        self.assertIsNone(page.events[0].text)

    def test_upsert_without_text_fails_closed(self):
        row = event(text=None)
        client = FakeClient(200, json.dumps({"events": [row], "has_more": False}).encode())
        with self.assertRaisesRegex(FeedError, "malformed"):
            RadarDocumentFeedClient(self.config(), client).fetch()

    def test_has_more_requires_cursor_and_http_errors_are_visible(self):
        bad_page = FakeClient(200, b'{"events": [], "has_more": true}')
        with self.assertRaisesRegex(FeedError, "malformed"):
            RadarDocumentFeedClient(self.config(), bad_page).fetch()
        with self.assertRaisesRegex(FeedError, "HTTP 503"):
            RadarDocumentFeedClient(self.config(), FakeClient(503, b"")).fetch()

    def test_nonempty_final_page_requires_checkpoint_cursor(self):
        client = FakeClient(200, json.dumps({"events": [event()], "has_more": False}).encode())
        with self.assertRaisesRegex(FeedError, "malformed"):
            RadarDocumentFeedClient(self.config(), client).fetch()


if __name__ == "__main__":
    unittest.main()
