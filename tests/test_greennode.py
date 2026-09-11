import json
import unittest

from radar_intelligence.providers import GreenNodeConfig, GreenNodeTransport, ProviderError


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.call = None

    def post(self, url, headers, body, timeout_seconds):
        self.call = (url, headers, json.loads(body), timeout_seconds)
        return self.response


class GreenNodeTest(unittest.TestCase):
    def test_openai_compatible_contract_and_usage(self):
        client = FakeHttp(json.dumps({
            "id": "req-1",
            "choices": [{"message": {"content": "grounded answer"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        }).encode())
        transport = GreenNodeTransport(GreenNodeConfig("https://green.example/v1/", "secret"), client)
        response = transport.complete(model="fast-alias", text="question", timeout_seconds=7)
        url, headers, body, timeout = client.call
        self.assertEqual(url, "https://green.example/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(body["model"], "fast-alias")
        self.assertEqual(body["messages"], [{"role": "user", "content": "question"}])
        self.assertEqual(timeout, 7)
        self.assertEqual((response.input_tokens, response.output_tokens), (12, 4))
        self.assertEqual(response.request_id, "req-1")

    def test_malformed_response_fails_closed(self):
        transport = GreenNodeTransport(GreenNodeConfig("https://green.example/v1", "secret"), FakeHttp(b"{}"))
        with self.assertRaisesRegex(ProviderError, "malformed"):
            transport.complete(model="deep", text="question", timeout_seconds=5)

    def test_requires_https_and_key(self):
        with self.assertRaises(ValueError):
            GreenNodeConfig("http://green.example/v1", "secret")
        with self.assertRaises(ValueError):
            GreenNodeConfig("https://green.example/v1", "")


if __name__ == "__main__":
    unittest.main()
