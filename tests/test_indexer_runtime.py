import os
import unittest
from unittest.mock import patch

from radar_intelligence.indexing.__main__ import _ProviderFallbackIndexer, _positive_number, build_coordinator
from radar_intelligence.providers import ProviderError
from radar_intelligence.config import RuntimeSettings


class IndexerRuntimeTest(unittest.TestCase):
    def test_provider_failure_falls_back_to_lexical_indexer(self):
        class Primary:
            def apply(self, change):
                raise ProviderError("GreenNode HTTP 429")

        class Lexical:
            def apply(self, change):
                return ("lexical", change)

        self.assertEqual(
            _ProviderFallbackIndexer(Primary(), Lexical()).apply("event"),
            ("lexical", "event"),
        )

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
