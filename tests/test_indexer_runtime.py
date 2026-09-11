import os
import unittest
from unittest.mock import patch

from radar_intelligence.indexing.__main__ import _positive_number, build_coordinator
from radar_intelligence.config import RuntimeSettings


class IndexerRuntimeTest(unittest.TestCase):
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
