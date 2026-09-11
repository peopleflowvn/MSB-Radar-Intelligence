import tempfile
import unittest
from pathlib import Path

from radar_intelligence.evaluation import DatasetContractError, load_jsonl_dataset


class EvaluationDatasetTest(unittest.TestCase):
    def _load(self, content: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gold.jsonl"
            path.write_text(content, encoding="utf-8")
            return load_jsonl_dataset(path)

    def test_repository_coverage_seed_has_50_unscored_cases(self):
        path = Path(__file__).parents[1] / "evaluation" / "datasets" / "radar_gold_v1.jsonl"
        dataset = load_jsonl_dataset(path)
        self.assertEqual(len(dataset.cases), 50)
        self.assertEqual(dataset.scored_cases, ())
        self.assertEqual(len(dataset.sha256), 64)

    def test_explicit_empty_truth_is_a_scored_no_result_case(self):
        dataset = self._load(
            '{"id":"n1","category":"NO_RESULT","query":"none","expected_path":"hybrid",'
            '"source":"review","relevant_person_ids":[]}\n'
        )
        self.assertTrue(dataset.cases[0].is_scored)
        self.assertEqual(dataset.cases[0].relevant_person_ids, ())

    def test_duplicate_ids_and_unknown_fields_are_rejected(self):
        row = '{"id":"a","category":"C","query":"q","expected_path":"hybrid","source":"s"}\n'
        with self.assertRaisesRegex(DatasetContractError, "duplicate id"):
            self._load(row + row)
        with self.assertRaisesRegex(DatasetContractError, "unknown fields: expected_name"):
            self._load(row.rstrip()[:-1] + ',"expected_name":"guess"}\n')

    def test_malformed_truth_is_rejected(self):
        row = (
            '{"id":"a","category":"C","query":"q","expected_path":"hybrid","source":"s",'
            '"relevant_person_ids":["p1","p1"]}\n'
        )
        with self.assertRaisesRegex(DatasetContractError, "contains duplicates"):
            self._load(row)


if __name__ == "__main__":
    unittest.main()
