import unittest

from radar_intelligence.evaluation import evaluate_retrieval


class EvaluationTest(unittest.TestCase):
    def test_retrieval_metrics_use_explicit_truth(self):
        metrics = evaluate_retrieval([
            ({"p2"}, ["p1", "p2", "p3"]),
            ({"p4", "p5"}, ["p4", "p8", "p9"]),
        ], k=3)
        self.assertEqual(metrics.cases, 2)
        self.assertAlmostEqual(metrics.recall_at_k, 0.75)
        self.assertAlmostEqual(metrics.precision_at_k, 1 / 3)
        self.assertAlmostEqual(metrics.mean_reciprocal_rank, 0.75)

    def test_no_result_is_measured_separately(self):
        metrics = evaluate_retrieval([(set(), []), (set(), ["p1"])], k=5)
        self.assertEqual(metrics.no_result_cases, 2)
        self.assertEqual(metrics.no_result_accuracy, 0.5)


if __name__ == "__main__":
    unittest.main()
