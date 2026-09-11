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

    def test_liveness_is_independent_of_external_configuration(self):
        with urllib.request.urlopen(self.base + "/health") as response:
            body = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(body["status"], "ok")

    def test_readiness_reports_missing_names_without_values(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.base + "/ready")
        self.assertEqual(caught.exception.code, 503)
        body = json.loads(caught.exception.read())
        caught.exception.close()
        self.assertEqual(body["status"], "not_ready")
        self.assertIn("RADAR_SERVICE_TOKEN", body["missing"])


if __name__ == "__main__":
    unittest.main()
