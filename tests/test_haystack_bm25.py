from __future__ import annotations

import os
import unittest

os.environ["HAYSTACK_TELEMETRY_ENABLED"] = "false"

try:
    import haystack  # noqa: F401
except ImportError:
    haystack = None

from radar_intelligence.contracts import Evidence, PersonRef
from radar_intelligence.retrieval import CandidateChunk, HaystackBM25Ranker, RetrievalRecord


def record(person_id, evidence_id, text):
    return RetrievalRecord(CandidateChunk(
        PersonRef(person_id, person_id),
        Evidence(evidence_id, person_id, "d" + evidence_id, "cv", text, "page 1", 1.0, "sha", "1"),
    ))


@unittest.skipIf(haystack is None, "Haystack optional dependency is not installed")
class HaystackBM25Test(unittest.TestCase):
    def test_candidate_limit_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "candidate_limit"):
            HaystackBM25Ranker(0)

    def test_bm25_ranks_accent_insensitive_content(self):
        scores = HaystackBM25Ranker().rank("kế toán", [
            record("p1", "e1", "Chuyên viên kế toán tại Đà Nẵng"),
            record("p2", "e2", "Kỹ sư phần mềm Java"),
        ])
        self.assertEqual(scores[0][0], "e1")
        self.assertNotIn("e2", [evidence_id for evidence_id, _ in scores])

    def test_bm25_only_returns_ids_from_input(self):
        records = [record("p1", "e1", "SQL banking")]
        self.assertEqual({identifier for identifier, _ in HaystackBM25Ranker().rank("SQL", records)}, {"e1"})

    def test_prepared_lexical_corpus_is_reused(self):
        records = [record("p1", "e1", "SQL banking")]
        ranker = HaystackBM25Ranker()
        ranker.prepare(records)
        prepared = ranker._prepared_records
        ranker.rank("SQL", records)
        self.assertIs(ranker._prepared_records, prepared)
