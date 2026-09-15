from __future__ import annotations

import logging
import unittest

from radar_intelligence.api.search_service import (
    _MAX_CONTEXT_CHARS, SearchService, _bounded_context, _parse_grounded_json,
)
from radar_intelligence.contracts import AnswerRequest, Evidence, PersonRef, SearchRequest
from radar_intelligence.providers import Capability, GatewayResponse, ModelGateway
from radar_intelligence.retrieval import CandidateChunk, HybridRetriever, RetrievalRecord
from radar_intelligence.websearch import WebSearchConfig


class ParseGroundedJsonTest(unittest.TestCase):
    def test_strict_json_parses_directly(self):
        parsed = _parse_grounded_json('{"answer":"ok","cited_evidence_ids":["e1"]}')
        self.assertEqual(parsed, {"answer": "ok", "cited_evidence_ids": ["e1"]})

    def test_markdown_fence_is_stripped(self):
        text = '```json\n{"answer":"ok","cited_evidence_ids":["e1"]}\n```'
        self.assertEqual(_parse_grounded_json(text), {"answer": "ok", "cited_evidence_ids": ["e1"]})

    def test_bare_fence_without_json_label_is_stripped(self):
        text = '```\n{"answer":"ok","cited_evidence_ids":[]}\n```'
        self.assertEqual(_parse_grounded_json(text), {"answer": "ok", "cited_evidence_ids": []})

    def test_leading_prose_before_object_is_recovered(self):
        text = 'Here is the answer:\n{"answer":"ok","cited_evidence_ids":["e1"]}\nThanks.'
        self.assertEqual(_parse_grounded_json(text), {"answer": "ok", "cited_evidence_ids": ["e1"]})

    def test_non_object_json_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "malformed"):
            _parse_grounded_json("[1, 2, 3]")

    def test_unparseable_text_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "malformed"):
            _parse_grounded_json("I cannot help with that.")


class Row:
    def __init__(self, evidence_id, person_id, text):
        self.evidence_id, self.person_id, self.text = evidence_id, person_id, text


class BoundedContextTest(unittest.TestCase):
    def test_all_evidence_is_kept_under_the_budget(self):
        evidence = [Row(f"e{i}", "p1", "short text") for i in range(5)]
        context = _bounded_context(evidence)
        self.assertEqual(len(context), 5)

    def test_context_is_capped_once_the_character_budget_is_reached(self):
        big_text = "x" * (_MAX_CONTEXT_CHARS // 2 + 1)
        evidence = [Row("e1", "p1", big_text), Row("e2", "p1", big_text), Row("e3", "p1", big_text)]
        context = _bounded_context(evidence)
        self.assertEqual(len(context), 2)
        self.assertEqual([item["evidence_id"] for item in context], ["e1", "e2"])


def _web_fallback_transport(status_by_prefix):
    def transport(method, url, *, headers, body, timeout_seconds):
        for prefix, response in status_by_prefix.items():
            if prefix in url:
                return response
        raise AssertionError(f"unexpected url {url}")
    return transport


class _SynthesisTransport:
    def __init__(self, text):
        self.text = text

    def complete(self, *, model, text, timeout_seconds):
        return GatewayResponse(self.text, "greennode", model)


class _NoEvidenceStub:
    """Minimal stand-in exposing only what _agent_no_evidence reads from self."""

    def __init__(self, websearch_config, gateway, transport=None):
        self._websearch_config = websearch_config
        self._gateway = gateway
        self._websearch_transport = transport
        self._logger = logging.getLogger("test-no-evidence-stub")


class AgentNoEvidenceTest(unittest.TestCase):
    def _gateway(self, synthesis_text):
        return ModelGateway({
            Capability.FAST: "fast", Capability.DEEP: "deep",
            Capability.VISION: "vision", Capability.EMBEDDING: "embed",
        }, _SynthesisTransport(synthesis_text))

    def test_falls_back_to_web_when_no_evidence_and_no_pii(self):
        ddg_html = (
            '<a class="result__a" href="https://example.com">Example</a>'
            '<a class="result__snippet" href="x">Vi du snippet</a>')
        config = WebSearchConfig.from_env({"INTELLIGENCE_WEBSEARCH_BACKENDS": "duckduckgo"})
        transport = _web_fallback_transport({"html.duckduckgo.com": (200, ddg_html.encode())})
        stub = _NoEvidenceStub(config, self._gateway("cau tra loi tu web"), transport)
        state = {"request": AnswerRequest("Tong giam doc MSB la ai", "scope", "u1")}
        result = SearchService._agent_no_evidence(stub, state)
        body = result["result"]
        self.assertEqual(body["answer"], "cau tra loi tu web")
        self.assertFalse(body["interpreted_query"]["grounded"])
        self.assertEqual(body["interpreted_query"]["source"], "web")
        self.assertEqual(body["evidence"], [])

    def test_pii_in_question_never_reaches_web_search(self):
        config = WebSearchConfig.from_env({"INTELLIGENCE_WEBSEARCH_BACKENDS": "duckduckgo"})
        calls = []

        def _tracking(method, url, *, headers, body, timeout_seconds):
            calls.append(url)
            return 200, b""

        stub = _NoEvidenceStub(config, self._gateway("unused"), _tracking)
        state = {"request": AnswerRequest("email nguyenvana@gmail.com tung lam o dau", "scope", "u1")}
        result = SearchService._agent_no_evidence(stub, state)
        body = result["result"]
        self.assertEqual(calls, [])
        self.assertIn("Không tìm thấy bằng chứng", body["answer"])
        self.assertTrue(body["interpreted_query"]["grounded"])

    def test_web_search_disabled_falls_back_to_refusal(self):
        config = WebSearchConfig.from_env({"INTELLIGENCE_WEBSEARCH_ENABLED": "0"})
        stub = _NoEvidenceStub(config, self._gateway("unused"))
        state = {"request": AnswerRequest("thoi tiet hom nay", "scope", "u1")}
        result = SearchService._agent_no_evidence(stub, state)
        body = result["result"]
        self.assertIn("Không tìm thấy bằng chứng", body["answer"])


class _AlwaysValidScope:
    def validate(self, scope_token):
        return True


class _SearchNarrowingStub:
    """Minimal stand-in exposing only what SearchService.search reads from self."""

    def __init__(self, records):
        self._scope = _AlwaysValidScope()
        self._records = records
        self._retriever = HybridRetriever()

    def _current_records(self):
        return self._records


def _record(person_id, evidence_id, text, document_id=None):
    person = PersonRef(person_id, person_id)
    evidence = Evidence(evidence_id, person_id, document_id or f"d-{evidence_id}",
                        "cv", text, "page 1", 0.9, "sha", "1")
    return RetrievalRecord(CandidateChunk(person, evidence))


class SearchPersonIdsNarrowingTest(unittest.TestCase):
    def test_no_person_ids_searches_the_whole_authorized_corpus(self):
        records = (_record("p1", "e1", "python engineer"), _record("p2", "e2", "python engineer"))
        stub = _SearchNarrowingStub(records)
        request = SearchRequest("python", "scope", "u1")
        hits = SearchService.search(stub, request)
        self.assertEqual({hit["person"]["person_id"] for hit in hits}, {"p1", "p2"})

    def test_person_ids_narrows_results_to_exactly_those_people(self):
        records = (_record("p1", "e1", "python engineer"), _record("p2", "e2", "python engineer"))
        stub = _SearchNarrowingStub(records)
        request = SearchRequest("python", "scope", "u1", person_ids=("p1",))
        hits = SearchService.search(stub, request)
        self.assertEqual([hit["person"]["person_id"] for hit in hits], ["p1"])

    def test_person_ids_naming_a_nonexistent_person_yields_no_hits(self):
        records = (_record("p1", "e1", "python engineer"),)
        stub = _SearchNarrowingStub(records)
        request = SearchRequest("python", "scope", "u1", person_ids=("does-not-exist",))
        self.assertEqual(SearchService.search(stub, request), [])

    def test_invalid_scope_token_is_still_denied_before_narrowing_is_applied(self):
        class _AlwaysDenyScope:
            def validate(self, scope_token):
                return False

        stub = _SearchNarrowingStub((_record("p1", "e1", "python engineer"),))
        stub._scope = _AlwaysDenyScope()
        request = SearchRequest("python", "scope", "u1", person_ids=("p1",))
        self.assertIsNone(SearchService.search(stub, request))


class KnowledgeIdsScopingTest(unittest.TestCase):
    """A record whose person_id starts with '-' represents a non-candidate
    entity (e.g. an internal-knowledge document). It must never appear just
    because the candidate corpus is unrestricted."""

    def test_knowledge_record_is_excluded_by_default_even_with_open_candidate_scope(self):
        records = (_record("p1", "e1", "python engineer"),
                   _record("-5", "e2", "chinh sach nhan su noi bo"))
        stub = _SearchNarrowingStub(records)
        request = SearchRequest("nhan su", "scope", "u1")
        hits = SearchService.search(stub, request)
        self.assertEqual([hit["person"]["person_id"] for hit in hits], [])

    def test_knowledge_ids_explicitly_opts_a_document_back_in(self):
        records = (_record("p1", "e1", "python engineer"),
                   _record("-5", "e2", "chinh sach nhan su noi bo"))
        stub = _SearchNarrowingStub(records)
        request = SearchRequest("nhan su", "scope", "u1", knowledge_ids=("-5",))
        hits = SearchService.search(stub, request)
        self.assertEqual([hit["person"]["person_id"] for hit in hits], ["-5"])

    def test_candidate_narrowing_and_knowledge_ids_compose_independently(self):
        records = (_record("p1", "e1", "python"), _record("p2", "e2", "python"),
                   _record("-5", "e3", "python policy"))
        stub = _SearchNarrowingStub(records)
        request = SearchRequest("python", "scope", "u1",
                                person_ids=("p1",), knowledge_ids=("-5",))
        hits = SearchService.search(stub, request)
        self.assertEqual(sorted(hit["person"]["person_id"] for hit in hits), ["-5", "p1"])
        self.assertNotIn("p2", [hit["person"]["person_id"] for hit in hits])

    def test_knowledge_only_drops_every_candidate_record(self):
        records = (_record("p1", "e1", "quy trinh nghi phep cua ung vien"),
                   _record("-5", "e2", "quy trinh nghi phep cong ty"))
        stub = _SearchNarrowingStub(records)
        request = SearchRequest("quy trinh nghi phep", "scope", "u1",
                                knowledge_ids=("-5",), knowledge_only=True)
        hits = SearchService.search(stub, request)
        self.assertEqual([hit["person"]["person_id"] for hit in hits], ["-5"])

    def test_knowledge_only_without_allowlist_returns_nothing(self):
        records = (_record("p1", "e1", "python"), _record("-5", "e2", "python policy"))
        stub = _SearchNarrowingStub(records)
        request = SearchRequest("python", "scope", "u1", knowledge_only=True)
        self.assertEqual(SearchService.search(stub, request), [])

    def test_unlisted_knowledge_document_stays_excluded_even_under_narrowing(self):
        records = (_record("-5", "e1", "python policy"), _record("-9", "e2", "python other"))
        stub = _SearchNarrowingStub(records)
        request = SearchRequest("python", "scope", "u1", knowledge_ids=("-5",))
        hits = SearchService.search(stub, request)
        self.assertEqual([hit["person"]["person_id"] for hit in hits], ["-5"])


if __name__ == "__main__":
    unittest.main()
