from __future__ import annotations

import unittest

from radar_intelligence.api.search_service import _ProviderResilientSemanticRanker
from radar_intelligence.providers import ProviderError


class ProviderResilientSemanticRankerTest(unittest.TestCase):
    def test_provider_failure_degrades_to_lexical_without_logging_query(self):
        class UnavailableRanker:
            def rank(self, query, records):
                raise ProviderError("GreenNode HTTP 429")

        ranker = _ProviderResilientSemanticRanker(UnavailableRanker())
        with self.assertLogs("radar_intelligence.api.search_service", "WARNING") as logs:
            self.assertEqual(ranker.rank("sensitive query", ()), ())
        self.assertIn("semantic retrieval temporarily unavailable", logs.output[0])
        self.assertNotIn("sensitive query", logs.output[0])

    def test_non_provider_failure_remains_visible(self):
        class BrokenRanker:
            def rank(self, query, records):
                raise ValueError("invalid embedding")

        with self.assertRaisesRegex(ValueError, "invalid embedding"):
            _ProviderResilientSemanticRanker(BrokenRanker()).rank("query", ())


if __name__ == "__main__":
    unittest.main()
