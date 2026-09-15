from __future__ import annotations

import json
import unittest

from radar_intelligence.providers import Capability, GatewayResponse, ModelGateway, ProviderError
from radar_intelligence.websearch.backends import WebSearchConfig
from radar_intelligence.websearch.service import web_answer


class FakeTransport:
    """Implements the gateway Transport protocol for a fake FAST model."""

    def __init__(self, text="synthesized answer", raise_error=False):
        self.text = text
        self.raise_error = raise_error
        self.calls = []

    def complete(self, *, model, text, timeout_seconds):
        self.calls.append((model, text, timeout_seconds))
        if self.raise_error:
            raise ProviderError("GreenNode HTTP 500")
        return GatewayResponse(self.text, "greennode", model)


def _gateway(transport):
    return ModelGateway({
        Capability.FAST: "fast-alias", Capability.DEEP: "deep-alias",
        Capability.VISION: "vision-alias", Capability.EMBEDDING: "embed-alias",
    }, transport)


def _http_transport(responses):
    def transport(method, url, *, headers, body, timeout_seconds):
        for prefix, response in responses.items():
            if prefix in url:
                return response
        raise AssertionError(f"unexpected url {url}")
    return transport


class WebAnswerTest(unittest.TestCase):
    def test_empty_question_is_rejected(self):
        with self.assertRaises(Exception):
            web_answer("", system="s", config=WebSearchConfig.from_env({}), gateway=_gateway(FakeTransport()))

    def test_disabled_config_is_unavailable(self):
        config = WebSearchConfig.from_env({"INTELLIGENCE_WEBSEARCH_ENABLED": "0"})
        with self.assertRaises(Exception):
            web_answer("q", system="s", config=config, gateway=_gateway(FakeTransport()))

    def test_generic_backend_hits_are_synthesized_by_the_gateway(self):
        payload = json.dumps({"results": [
            {"title": "T", "url": "https://example.com", "content": "snippet"}]}).encode()
        config = WebSearchConfig.from_env({
            "TAVILY_API_KEY": "k", "INTELLIGENCE_WEBSEARCH_BACKENDS": "tavily"})
        http = _http_transport({"api.tavily.com": (200, payload)})
        gateway_transport = FakeTransport("day la cau tra loi")
        result = web_answer(
            "cau hoi", system="s", config=config, gateway=_gateway(gateway_transport),
            transport=http)
        self.assertEqual(result.text, "day la cau tra loi")
        self.assertEqual(result.provider, "tavily")
        self.assertEqual(result.citations[0]["url"], "https://example.com")
        # The raw web content must reach the model wrapped, not as bare instructions.
        prompt = gateway_transport.calls[0][1]
        self.assertIn("<<<", prompt)

    def test_grounded_backend_short_circuits_the_gateway(self):
        payload = json.dumps({"candidates": [{
            "content": {"parts": [{"text": "grounded answer"}]},
            "groundingMetadata": {"groundingChunks": []},
        }]}).encode()
        config = WebSearchConfig.from_env({
            "GEMINI_API_KEY": "k", "INTELLIGENCE_WEBSEARCH_BACKENDS": "gemini_grounding"})
        http = _http_transport({"generativelanguage.googleapis.com": (200, payload)})
        gateway_transport = FakeTransport()
        result = web_answer(
            "cau hoi", system="s", config=config, gateway=_gateway(gateway_transport),
            transport=http)
        self.assertEqual(result.text, "grounded answer")
        self.assertEqual(result.provider, "gemini_grounding")
        self.assertEqual(gateway_transport.calls, [])  # never called: Gemini answers directly

    def test_backend_failure_falls_through_to_the_next_backend(self):
        tavily_payload = json.dumps({"results": []}).encode()  # no hits -> unavailable
        brave_payload = json.dumps({"web": {"results": [
            {"title": "T", "url": "https://example.com", "description": "d"}]}}).encode()
        config = WebSearchConfig.from_env({
            "TAVILY_API_KEY": "k", "BRAVE_SEARCH_API_KEY": "b",
            "INTELLIGENCE_WEBSEARCH_BACKENDS": "tavily,brave"})
        http = _http_transport({
            "api.tavily.com": (200, tavily_payload),
            "api.search.brave.com": (200, brave_payload)})
        result = web_answer(
            "cau hoi", system="s", config=config, gateway=_gateway(FakeTransport("ok")),
            transport=http)
        self.assertEqual(result.provider, "brave")

    def test_synthesis_provider_failure_falls_through(self):
        payload = json.dumps({"results": [
            {"title": "T", "url": "https://example.com", "content": "snippet"}]}).encode()
        config = WebSearchConfig.from_env({
            "TAVILY_API_KEY": "k", "INTELLIGENCE_WEBSEARCH_BACKENDS": "tavily"})
        http = _http_transport({"api.tavily.com": (200, payload)})
        with self.assertRaises(Exception):
            web_answer(
                "cau hoi", system="s", config=config,
                gateway=_gateway(FakeTransport(raise_error=True)), transport=http)


if __name__ == "__main__":
    unittest.main()
