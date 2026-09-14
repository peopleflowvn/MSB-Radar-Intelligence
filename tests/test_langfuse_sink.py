import os
import unittest
from unittest.mock import patch

from radar_intelligence.observability.langfuse_sink import safe_span


class LangfuseSinkTests(unittest.TestCase):
    def test_disabled_without_complete_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with safe_span("answer", {"evidence_count": 2}) as span:
                self.assertIsNone(span)

    def test_application_errors_are_not_swallowed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "application failure"):
                with safe_span("answer"):
                    raise RuntimeError("application failure")


if __name__ == "__main__":
    unittest.main()
