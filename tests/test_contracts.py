import unittest

from radar_intelligence.contracts import Evidence, SearchFilters, SearchRequest


class ContractTest(unittest.TestCase):
    def test_search_requires_authorized_scope(self) -> None:
        with self.assertRaises(ValueError):
            SearchRequest(query="data analyst", scope_token="", principal_id="u1")

    def test_experience_range_must_be_coherent(self) -> None:
        with self.assertRaises(ValueError):
            SearchFilters(min_years_experience=5, max_years_experience=2)

    def test_evidence_score_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            Evidence("e1", "p1", "d1", "cv", "text", "page 1", 1.5, "sha", "1")


if __name__ == "__main__":
    unittest.main()

