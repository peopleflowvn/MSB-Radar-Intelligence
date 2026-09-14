import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from radar_intelligence.documents import DoclingParser
from radar_intelligence.evaluation.ragas_adapter import RagasEvaluator


class OptionalToolingTests(unittest.TestCase):
    def test_docling_rejects_non_file_source(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "must be a file"):
                DoclingParser().convert_to_markdown(folder)

    def test_ragas_rejects_empty_dataset_before_loading_dependency(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            RagasEvaluator.evaluate([], [])

    def test_docling_dependency_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "cv.txt"
            source.write_text("example", encoding="utf-8")
            with patch.dict("sys.modules", {"docling": None}):
                with self.assertRaisesRegex(RuntimeError, "documents.*extra"):
                    DoclingParser().convert_to_markdown(source)


if __name__ == "__main__":
    unittest.main()
