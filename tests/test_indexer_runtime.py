import os
import unittest
from unittest.mock import patch

from radar_intelligence.indexing.__main__ import (
    _KNOWLEDGE_CURSOR_NAMESPACE, _KNOWLEDGE_FEED_PATH, _ProviderFallbackIndexer,
    _positive_number, build_coordinator,
)
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

    def test_knowledge_coordinator_targets_its_own_feed_path_and_cursor(self):
        import tempfile
        from pathlib import Path

        values = {
            "RADAR_BASE_URL": "https://radar.example", "RADAR_SERVICE_TOKEN": "radar-secret",
            "RADAR_INDEX_SCOPE_TOKEN": "scope-secret", "GREENNODE_BASE_URL": "https://green.example/v1",
            "GREENNODE_API_KEY": "green-secret", "GREENNODE_MODEL_FAST": "fast",
            "GREENNODE_MODEL_DEEP": "deep", "GREENNODE_MODEL_VISION": "vision",
            "GREENNODE_MODEL_EMBEDDING": "embedding",
        }
        settings = RuntimeSettings.from_env(values)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "index.sqlite3")
            with patch.dict(os.environ, {"INTELLIGENCE_INDEX_DB": db_path}):
                default_coordinator = build_coordinator(settings)
                knowledge_coordinator = build_coordinator(
                    settings, feed_path=_KNOWLEDGE_FEED_PATH,
                    cursor_namespace=_KNOWLEDGE_CURSOR_NAMESPACE)
        self.assertIn("document-feed", default_coordinator._feed._config.path)
        self.assertEqual(knowledge_coordinator._feed._config.path, _KNOWLEDGE_FEED_PATH)
        self.assertEqual(knowledge_coordinator._cursors._namespace, _KNOWLEDGE_CURSOR_NAMESPACE)


if __name__ == "__main__":
    unittest.main()
