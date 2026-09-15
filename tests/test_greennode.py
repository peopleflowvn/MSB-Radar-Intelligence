import json
import unittest
import urllib.error
from unittest.mock import patch

from radar_intelligence.providers import GreenNodeConfig, GreenNodeEmbedder, GreenNodeTransport, ProviderError, UrllibHttpClient


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.call = None

    def post(self, url, headers, body, timeout_seconds):
        self.call = (url, headers, json.loads(body), timeout_seconds)
        return self.response


def _http_error(code):
    return urllib.error.HTTPError("https://provider.example", code, "error", {}, None)


class UrllibHttpClientRetryTest(unittest.TestCase):
    def test_5xx_is_retried_like_429(self):
        attempts = [_http_error(503), _http_error(503), b"ok"]

        def fake_urlopen(request, timeout):
            outcome = attempts.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return _Response(outcome)

        with patch("time.sleep"), patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client = UrllibHttpClient(retry_attempts=3)
            result = client.post("https://provider.example", {}, b"{}", 5.0)
        self.assertEqual(result, b"ok")
        self.assertEqual(attempts, [])

    def test_5xx_exhausting_retries_raises_provider_error(self):
        with patch("time.sleep"), patch(
            "urllib.request.urlopen", side_effect=_http_error(500)
        ):
            with self.assertRaisesRegex(ProviderError, "GreenNode HTTP 500"):
                UrllibHttpClient(retry_attempts=2).post("https://provider.example", {}, b"{}", 5.0)

    def test_non_retryable_4xx_raises_on_first_attempt(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(1)
            raise _http_error(400)

        with patch("time.sleep") as sleep_mock, patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaisesRegex(ProviderError, "GreenNode HTTP 400"):
                UrllibHttpClient(retry_attempts=3).post("https://provider.example", {}, b"{}", 5.0)
        self.assertEqual(len(calls), 1)
        sleep_mock.assert_not_called()

    def test_network_error_is_retried(self):
        attempts = [urllib.error.URLError("boom"), b"ok"]

        def fake_urlopen(request, timeout):
            outcome = attempts.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return _Response(outcome)

        with patch("time.sleep"), patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = UrllibHttpClient(retry_attempts=2).post("https://provider.example", {}, b"{}", 5.0)
        self.assertEqual(result, b"ok")


class _Response:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class GreenNodeTest(unittest.TestCase):
    def test_retry_attempts_are_bounded(self):
        with self.assertRaisesRegex(ValueError, "retry_attempts"):
            UrllibHttpClient(0)
        with self.assertRaisesRegex(ValueError, "retry_attempts"):
            UrllibHttpClient(5)

    def test_embedding_timeout_must_be_positive(self):
        config = GreenNodeConfig("https://provider.example", "key")
        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            GreenNodeEmbedder(config, "embedding", timeout_seconds=0)

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

    def test_embedding_contract_preserves_input_order(self):
        client = FakeHttp(json.dumps({"data": [
            {"index": 1, "embedding": [0.0, 1.0]},
            {"index": 0, "embedding": [1.0, 0.0]},
        ]}).encode())
        embedder = GreenNodeEmbedder(GreenNodeConfig("https://green.example/v1", "secret"), "embed-alias", client)
        vectors = embedder.embed_documents(["first", "second"])
        self.assertEqual(vectors, [(1.0, 0.0), (0.0, 1.0)])
        self.assertEqual(client.call[0], "https://green.example/v1/embeddings")
        self.assertEqual(client.call[2], {"model": "embed-alias", "input": ["first", "second"]})

    def test_embedding_count_mismatch_fails_closed(self):
        client = FakeHttp(json.dumps({"data": [{"index": 0, "embedding": [1.0]}]}).encode())
        embedder = GreenNodeEmbedder(GreenNodeConfig("https://green.example/v1", "secret"), "embed", client)
        with self.assertRaisesRegex(ProviderError, "malformed embedding"):
            embedder.embed_documents(["first", "second"])


if __name__ == "__main__":
    unittest.main()
