import json
import unittest

from radar_intelligence.observability import OperationalTrace, TraceError


class ObservabilityTest(unittest.TestCase):
    def test_safe_trace_is_allow_listed_and_json_serializable(self):
        trace = OperationalTrace(
            request_id="r1", thread_id="t1", execution_class="SEARCH", status="ok",
            tools=("search_people",), retrieval_path=("structured", "bm25"),
            candidate_count=12, evidence_count=3, provider="greennode",
            model_alias="fast-default", input_tokens=100, output_tokens=20,
            latency_ms=250, fallback="none",
        )
        payload = trace.to_safe_dict()
        json.dumps(payload)
        self.assertNotIn("query", payload)
        self.assertNotIn("scope_token", payload)
        self.assertNotIn("chain_of_thought", payload)
        self.assertEqual(payload["candidate_count"], 12)

    def test_errors_expose_codes_not_exception_messages(self):
        trace = OperationalTrace(
            "r1", "SEARCH", "failed",
            errors=(TraceError("MODEL_TIMEOUT", "greennode", True),),
        )
        self.assertEqual(trace.to_safe_dict()["errors"], [
            {"code": "MODEL_TIMEOUT", "dependency": "greennode", "retryable": True}
        ])

    def test_counts_and_tokens_must_be_non_negative_integers(self):
        with self.assertRaisesRegex(ValueError, "candidate_count"):
            OperationalTrace("r1", "SEARCH", "ok", candidate_count=-1)
        with self.assertRaisesRegex(ValueError, "input_tokens"):
            OperationalTrace("r1", "SEARCH", "ok", input_tokens=True)


if __name__ == "__main__":
    unittest.main()
