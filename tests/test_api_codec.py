import json
import unittest

from radar_intelligence.api import (
    ApiContractError, decode_answer_request, decode_search_request,
    encode_answer_response, encode_search_hit,
)
from radar_intelligence.contracts import AnswerResponse, Evidence, ModelTrace, PersonRef, SearchHit


class ApiCodecTest(unittest.TestCase):
    def test_search_request_decodes_strict_nested_contract(self):
        request = decode_search_request({
            "query": "data analyst", "scope_token": "opaque", "principal_id": "u1",
            "filters": {"locations": ["Ha Noi"], "min_years_experience": 3}, "limit": 20,
        })
        self.assertEqual(request.filters.locations, ("Ha Noi",))
        self.assertEqual(request.filters.min_years_experience, 3.0)

    def test_unknown_top_level_and_filter_fields_are_rejected(self):
        base = {"query": "q", "scope_token": "s", "principal_id": "u"}
        with self.assertRaisesRegex(ApiContractError, "unknown fields: role"):
            decode_search_request({**base, "role": "admin"})
        with self.assertRaisesRegex(ApiContractError, "unknown fields: unrestricted"):
            decode_search_request({**base, "filters": {"unrestricted": True}})

    def test_wrong_types_and_bool_limit_are_rejected(self):
        base = {"query": "q", "scope_token": "s", "principal_id": "u"}
        with self.assertRaisesRegex(ApiContractError, "limit must be an integer"):
            decode_search_request({**base, "limit": True})
        with self.assertRaisesRegex(ApiContractError, "locations must be an array"):
            decode_search_request({**base, "filters": {"locations": "all"}})

    def test_search_request_decodes_optional_person_ids_narrowing(self):
        request = decode_search_request({
            "query": "q", "scope_token": "s", "principal_id": "u",
            "person_ids": ["p1", "p2"],
        })
        self.assertEqual(request.person_ids, ("p1", "p2"))

    def test_search_request_person_ids_defaults_to_empty(self):
        request = decode_search_request({"query": "q", "scope_token": "s", "principal_id": "u"})
        self.assertEqual(request.person_ids, ())

    def test_search_request_rejects_non_string_person_ids(self):
        base = {"query": "q", "scope_token": "s", "principal_id": "u"}
        with self.assertRaisesRegex(ApiContractError, "array of strings"):
            decode_search_request({**base, "person_ids": [1]})

    def test_search_request_decodes_knowledge_ids(self):
        request = decode_search_request({
            "query": "q", "scope_token": "s", "principal_id": "u",
            "knowledge_ids": ["-1", "-2"],
        })
        self.assertEqual(request.knowledge_ids, ("-1", "-2"))

    def test_search_request_decodes_knowledge_only_flag(self):
        base = {"query": "q", "scope_token": "s", "principal_id": "u"}
        self.assertFalse(decode_search_request(base).knowledge_only)
        self.assertTrue(decode_search_request({**base, "knowledge_only": True}).knowledge_only)
        with self.assertRaisesRegex(ApiContractError, "knowledge_only must be a boolean"):
            decode_search_request({**base, "knowledge_only": "yes"})

    def test_answer_request_decodes_knowledge_ids(self):
        request = decode_answer_request({
            "question": "q", "scope_token": "s", "principal_id": "u",
            "knowledge_ids": ["-1"],
        })
        self.assertEqual(request.knowledge_ids, ("-1",))

    def test_answer_request_requires_scope_and_string_person_ids(self):
        with self.assertRaisesRegex(ApiContractError, "missing fields: scope_token"):
            decode_answer_request({"question": "q", "principal_id": "u"})
        with self.assertRaisesRegex(ApiContractError, "array of strings"):
            decode_answer_request({
                "question": "q", "scope_token": "s", "principal_id": "u", "person_ids": [1]
            })

    def test_response_encoders_produce_json_and_only_contract_fields(self):
        evidence = Evidence("e1", "p1", "d1", "cv", "SQL", "page 1", .9, "sha", "v1")
        hit = SearchHit(PersonRef("p1", "An"), .8, (evidence,), ("locations",))
        encoded_hit = encode_search_hit(hit)
        self.assertEqual(set(encoded_hit), {"person", "score", "evidence", "matched_filters"})
        response = AnswerResponse(
            "Answer", (hit.person,), (evidence,), ("e1",), {"skills": ["SQL"]},
            (ModelTrace("answer", "greennode", "answer-default", 12, request_id="r1"),),
        )
        payload = encode_answer_response(response)
        json.dumps(payload)
        self.assertEqual(payload["trace"][0]["model_alias"], "answer-default")

    def test_response_rejects_non_json_interpreted_query(self):
        response = AnswerResponse("a", (), (), (), {"bad": object()})
        with self.assertRaisesRegex(ApiContractError, "non-JSON"):
            encode_answer_response(response)


if __name__ == "__main__":
    unittest.main()
