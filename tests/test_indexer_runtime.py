import os
import unittest
from unittest.mock import patch

from radar_intelligence.indexing.__main__ import _ProviderFallbackIndexer, _positive_number, build_coordinator
from radar_intelligence.providers import ProviderError
from radar_intelligence.config import RuntimeSettings


class IndexerRuntimeTest(unittest.TestCase):
    def test_provider_failure_falls_back_to_lexical_indexer(self):
        class Primary:
            calls = 0

            def apply(self, change):
                self.calls += 1
                raise ProviderError("GreenNode HTTP 429")

        class Lexical:
            calls = 0

            def apply(self, change):
                self.calls += 1
                return ("lexical", change)

        primary = Primary()
        lexical = Lexical()
        indexer = _ProviderFallbackIndexer(primary, lexical)
        self.assertEqual(
            indexer.apply("event"),
            ("lexical", "event"),
        )
        self.assertEqual(indexer.apply("next"), ("lexical", "next"))
        self.assertEqual(primary.calls, 1)
        self.assertEqual(lexical.calls, 2)

    def test_positive_number_rejects_invalid_runtime_values(self):
        with patch.dict(os.environ, {"SYNC_VALUE": "0"}):
            with self.assertRaisesRegex(ValueError, "positive"):
                _positive_number("SYNC_VALUE", "1", int)

    def test_coordinator_fails_closed_when_runtime_is_incomplete(self):
        settings = RuntimeSettings.from_env({})
        with self.assertRaisesRegex(ValueError, "runtime settings incomplete"):
            build_coordinator(settings)


if __name__ == "__main__":
    unittest.main()
