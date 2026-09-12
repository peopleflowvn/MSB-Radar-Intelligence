from django.test import SimpleTestCase

from .brain_eval import gold_set, percentile, retrieval_metrics


class MetricValidityTest(SimpleTestCase):
    def test_missing_truth_is_not_perfect_recall(self):
        self.assertIsNone(retrieval_metrics([], [], 10)["recall_at_k"])

    def test_duplicate_hits_cannot_improve_precision(self):
        values = retrieval_metrics([1, 2], [1, 1], 2)
        self.assertEqual(values["recall_at_k"], .5)
        self.assertEqual(values["precision_at_k"], .5)
        self.assertEqual(values["duplicates"], 1)

    def test_missing_latency_is_not_zero(self):
        self.assertIsNone(percentile([], .95))
        self.assertEqual(percentile([10, 20, 30], .5), 20)

    def test_gold_ids_and_provenance_are_explicit(self):
        gold = gold_set()
        ids = {p["id"] for p in gold["people"]}
        self.assertEqual(len({c["id"] for c in gold["cases"]}), len(gold["cases"]))
        self.assertIn("synthetic", gold["truth_kind"])
        for case in gold["cases"]:
            self.assertTrue(set(case.get("expected_ids", [])) <= ids)
        self.assertGreaterEqual(len({t for c in gold["cases"] for t in c["tags"]}), 32)

    def test_public_trace_removes_nested_reasoning_preserves_measurements(self):
        from .public_trace import public_metadata
        private = {"reasoning_trace": "private", "trace": {"task": "judge", "latency_ms": 20,
                   "calls": [{"model": "fixture", "thinking": "private"}]}}
        public = public_metadata(private)
        self.assertNotIn("private", str(public))
        self.assertEqual(public["trace"]["latency_ms"], 20)
        self.assertIn("reasoning_trace", private)  # no destructive history rewrite
