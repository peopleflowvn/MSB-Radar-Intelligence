from __future__ import annotations

import json
import unittest

from radar_intelligence.websearch.backends import (
    BraveBackend,
    DuckDuckGoBackend,
    GeminiGroundingBackend,
    GoogleCseBackend,
    TavilyBackend,
    WebSearchConfig,
    WebSearchUnavailable,
    pick_backends,
)

_DDG_HTML = """
<div class="result results_links results_links_deep web-result">
  <div class="links_main links_deep result__body">
    <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsbv.gov.vn%2Fz&amp;rut=x">Ngan hang Nha nuoc</a>
    <a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">Thong tin ve <b>ngan hang</b> nha nuoc Viet Nam.</a>
  </div>
</div>
"""


def _fake_transport(responses):
    calls = []

    def transport(method, url, *, headers, body, timeout_seconds):
        calls.append((method, url, headers, body, timeout_seconds))
        for prefix, response in responses.items():
            if prefix in url:
                return response
        raise AssertionError(f"no fake response registered for {url}")

    transport.calls = calls
    return transport


class WebSearchConfigTest(unittest.TestCase):
    def test_defaults_come_from_environment(self):
        config = WebSearchConfig.from_env({
            "TAVILY_API_KEY": "k", "ASSISTANT_WEBSEARCH_BACKENDS_UNUSED": "x",
        })
        self.assertTrue(config.enabled)
        self.assertTrue(config.ddg_enabled)
        self.assertEqual(config.tavily_api_key, "k")

    def test_disabled_flag_is_respected(self):
        config = WebSearchConfig.from_env({"INTELLIGENCE_WEBSEARCH_ENABLED": "0"})
        self.assertFalse(config.enabled)

    def test_custom_backend_order_filters_unknown_names(self):
        config = WebSearchConfig.from_env({
            "INTELLIGENCE_WEBSEARCH_BACKENDS": "tavily,not_a_backend,brave"})
        self.assertEqual(config.backend_order, ("tavily", "brave"))


class DuckDuckGoBackendTest(unittest.TestCase):
    def test_parses_title_url_and_snippet(self):
        transport = _fake_transport({"html.duckduckgo.com": (200, _DDG_HTML.encode("utf-8"))})
        backend = DuckDuckGoBackend(WebSearchConfig.from_env({}), transport)
        result = backend.run("ngan hang nha nuoc", timeout_seconds=5.0)
        self.assertEqual(len(result.hits), 1)
        hit = result.hits[0]
        self.assertEqual(hit.title, "Ngan hang Nha nuoc")
        self.assertEqual(hit.url, "https://sbv.gov.vn/z")
        self.assertIn("ngan hang", hit.snippet)

    def test_unparseable_page_raises_unavailable(self):
        transport = _fake_transport({"html.duckduckgo.com": (200, b"<html>no results here</html>")})
        backend = DuckDuckGoBackend(WebSearchConfig.from_env({}), transport)
        with self.assertRaises(WebSearchUnavailable):
            backend.run("query", timeout_seconds=5.0)

    def test_http_error_raises_unavailable(self):
        transport = _fake_transport({"html.duckduckgo.com": (503, b"")})
        backend = DuckDuckGoBackend(WebSearchConfig.from_env({}), transport)
        with self.assertRaises(WebSearchUnavailable):
            backend.run("query", timeout_seconds=5.0)

    def test_disabled_via_env_is_unavailable(self):
        config = WebSearchConfig.from_env({"INTELLIGENCE_WEBSEARCH_DDG": "0"})
        self.assertFalse(DuckDuckGoBackend(config).available())


class TavilyBackendTest(unittest.TestCase):
    def test_requires_api_key_to_be_available(self):
        self.assertFalse(TavilyBackend(WebSearchConfig.from_env({})).available())
        self.assertTrue(TavilyBackend(WebSearchConfig.from_env({"TAVILY_API_KEY": "k"})).available())

    def test_parses_results(self):
        payload = json.dumps({"results": [
            {"title": "T", "url": "https://example.com", "content": "snippet"}]}).encode()
        transport = _fake_transport({"api.tavily.com": (200, payload)})
        backend = TavilyBackend(WebSearchConfig.from_env({"TAVILY_API_KEY": "k"}), transport)
        result = backend.run("q", timeout_seconds=5.0)
        self.assertEqual(result.hits[0].url, "https://example.com")


class BraveBackendTest(unittest.TestCase):
    def test_parses_web_results(self):
        payload = json.dumps({"web": {"results": [
            {"title": "T", "url": "https://example.com", "description": "d"}]}}).encode()
        transport = _fake_transport({"api.search.brave.com": (200, payload)})
        backend = BraveBackend(WebSearchConfig.from_env({"BRAVE_SEARCH_API_KEY": "k"}), transport)
        result = backend.run("q", timeout_seconds=5.0)
        self.assertEqual(result.hits[0].title, "T")


class GoogleCseBackendTest(unittest.TestCase):
    def test_requires_both_key_and_cx(self):
        self.assertFalse(GoogleCseBackend(WebSearchConfig.from_env({"GOOGLE_CSE_KEY": "k"})).available())
        self.assertTrue(GoogleCseBackend(
            WebSearchConfig.from_env({"GOOGLE_CSE_KEY": "k", "GOOGLE_CSE_CX": "c"})).available())


class GeminiGroundingBackendTest(unittest.TestCase):
    def test_extracts_text_and_citations(self):
        payload = json.dumps({"candidates": [{
            "content": {"parts": [{"text": "answer text"}]},
            "groundingMetadata": {
                "webSearchQueries": ["q1"],
                "groundingChunks": [{"web": {"uri": "https://x.example", "title": "X"}}],
            },
        }]}).encode()
        transport = _fake_transport({"generativelanguage.googleapis.com": (200, payload)})
        backend = GeminiGroundingBackend(
            WebSearchConfig.from_env({"GEMINI_API_KEY": "k"}), transport)
        result = backend.run("q", timeout_seconds=10.0, system="sys")
        self.assertEqual(result.text, "answer text")
        self.assertEqual(result.citations[0]["url"], "https://x.example")
        self.assertEqual(result.queries, ("q1",))

    def test_auth_failure_raises_unavailable(self):
        transport = _fake_transport({"generativelanguage.googleapis.com": (403, b"{}")})
        backend = GeminiGroundingBackend(WebSearchConfig.from_env({"GEMINI_API_KEY": "k"}), transport)
        with self.assertRaises(WebSearchUnavailable):
            backend.run("q", timeout_seconds=10.0)


class PickBackendsTest(unittest.TestCase):
    def test_only_available_backends_are_returned_in_priority_order(self):
        config = WebSearchConfig.from_env({
            "TAVILY_API_KEY": "k", "INTELLIGENCE_WEBSEARCH_BACKENDS": "gemini_grounding,tavily,duckduckgo"})
        names = [backend.name for backend in pick_backends(config)]
        self.assertEqual(names, ["tavily", "duckduckgo"])

    def test_no_backends_when_disabled_individually(self):
        config = WebSearchConfig.from_env({
            "INTELLIGENCE_WEBSEARCH_DDG": "0", "INTELLIGENCE_WEBSEARCH_BACKENDS": "duckduckgo"})
        self.assertEqual(pick_backends(config), ())


if __name__ == "__main__":
    unittest.main()
