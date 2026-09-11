import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from radar_intelligence.api.__main__ import Handler


class ApiHealthTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        Handler.search_service = None

    def test_liveness_is_independent_of_external_configuration(self):
        with patch.dict("os.environ", {"INTELLIGENCE_RELEASE_SHA": "abc123"}):
            with urllib.request.urlopen(self.base + "/health") as response:
                body = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["release_sha"], "abc123")

    def test_readiness_reports_missing_names_without_values(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.base + "/ready")
        self.assertEqual(caught.exception.code, 503)
        body = json.loads(caught.exception.read())
        caught.exception.close()
        self.assertEqual(body["status"], "not_ready")
        self.assertIn("RADAR_SERVICE_TOKEN", body["missing"])

    def test_search_requires_service_auth_and_forwards_strict_contract(self):
        class FakeSearch:
            request = None

            def search(self, request):
                self.request = request
                return []

            def answer(self, request):
                self.request = request
                return {"answer": "grounded", "people": [], "evidence": [],
                        "cited_evidence_ids": [], "interpreted_query": {}, "trace": []}

            def index_status(self):
                return {"events": 3, "documents": 2, "deleted": 1, "chunks": 5}

        service = FakeSearch()
        Handler.search_service = service
        payload = json.dumps({
            "query": "Python", "scope_token": "signed", "principal_id": "7",
        }).encode()

        def post(token):
            request = urllib.request.Request(
                self.base + "/v1/search", data=payload, method="POST",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            return urllib.request.urlopen(request)

        with patch.dict("os.environ", {"RADAR_SERVICE_TOKEN": "shared-secret"}, clear=True):
            with self.assertRaises(urllib.error.HTTPError) as denied:
                post("wrong")
            self.assertEqual(denied.exception.code, 404)
            denied.exception.close()
            with post("shared-secret") as response:
                body = json.loads(response.read())
        self.assertEqual(body, {"hits": []})
        self.assertEqual(service.request.scope_token, "signed")

        answer_payload = json.dumps({
            "question": "Ai phù hợp?", "scope_token": "signed", "principal_id": "7",
        }).encode()
        answer_request = urllib.request.Request(
            self.base + "/v1/answer", data=answer_payload, method="POST",
            headers={"Authorization": "Bearer shared-secret", "Content-Type": "application/json"})
        with patch.dict("os.environ", {"RADAR_SERVICE_TOKEN": "shared-secret"}, clear=True):
            with urllib.request.urlopen(answer_request) as response:
                answer = json.loads(response.read())
        self.assertEqual(answer["answer"], "grounded")
        self.assertEqual(service.request.question, "Ai phù hợp?")

        status_request = urllib.request.Request(
            self.base + "/index-status", headers={"Authorization": "Bearer shared-secret"})
        with patch.dict("os.environ", {"RADAR_SERVICE_TOKEN": "shared-secret"}, clear=True):
            with urllib.request.urlopen(status_request) as response:
                index_status = json.loads(response.read())
        self.assertEqual(index_status["documents"], 2)


if __name__ == "__main__":
    unittest.main()
