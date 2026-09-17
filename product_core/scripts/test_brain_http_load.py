import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from brain_http_load import probe, percentile


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        payload = {
            "/ok": b'event: answer\ndata: {"text":"ok"}\n\nevent: done\ndata: {}\n\n',
            "/error": b'event: error\ndata: {}\n\nevent: done\ndata: {}\n\n',
            "/incomplete": b'event: answer\ndata: {}\n\n',
        }[self.path]
        self.wfile.write(payload)


class LoadProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_completed_stream(self):
        row = probe(f"http://127.0.0.1:{self.server.server_port}/ok", "fixture", 2, {})
        self.assertTrue(row["ok"])
        self.assertIsNotNone(row["first_answer_ms"])

    def test_error_cannot_be_success(self):
        row = probe(f"http://127.0.0.1:{self.server.server_port}/error", "fixture", 2, {})
        self.assertFalse(row["ok"])
        self.assertEqual(row["error"], "sse_error")

    def test_truncated_stream(self):
        row = probe(f"http://127.0.0.1:{self.server.server_port}/incomplete", "fixture", 2, {})
        self.assertFalse(row["ok"])
        self.assertEqual(row["error"], "incomplete_stream")

    def test_percentile_excludes_unavailable(self):
        self.assertIsNone(percentile([], .95))
        self.assertEqual(percentile([100, 300], .95), 290)


if __name__ == "__main__":
    unittest.main()
