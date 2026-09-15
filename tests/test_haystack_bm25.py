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

    def test_retriever_is_reused_across_different_queries_for_the_same_corpus(self):
        records = [
            record("p1", "e1", "Chuyen vien ke toan"),
            record("p2", "e2", "Ky su phan mem"),
        ]
        ranker = HaystackBM25Ranker()
        ranker.rank("ke toan", records)
        retriever = ranker._prepared[2]
        ranker.rank("phan mem", records)
        self.assertIs(ranker._prepared[2], retriever)

    def test_scores_are_stable_across_queries_over_the_same_corpus(self):
        # A document with zero term overlap with the query must never be
        # ranked purely because a *different* query previously narrowed the
        # corpus used to compute term statistics (the corpus must be
        # query-independent, not just individually bounded).
        records = [
            record("p1", "e1", "Chuyen vien ke toan ngan hang"),
            record("p2", "e2", "Ky su phan mem Java"),
            record("p3", "e3", "Nhan vien ke toan kho"),
        ]
        ranker = HaystackBM25Ranker()
        first = dict(ranker.rank("ke toan", records))
        second = dict(ranker.rank("phan mem", records))
        self.assertEqual(set(first), {"e1", "e3"})
        self.assertEqual(set(second), {"e2"})

    def test_a_match_beyond_the_old_1000_cap_is_still_found(self):
        # Regression: candidate_limit used to default to 1_000 and silently
        # truncated the corpus to an arbitrary (evidence_id-sorted) slice
        # before indexing — a real production corpus this size (docs describe
        # "tens of thousands of chunks") made most candidates permanently
        # unreachable by lexical search regardless of query, since which slice
        # survives the sort depends only on hash order, not relevance.
        filler = [record(f"p{i}", f"e{i:05d}", "khong lien quan gi ca") for i in range(1500)]
        target = record("target", "zzzzz-target", "Chuyen vien ke toan ngan hang doc nhat")
        ranker = HaystackBM25Ranker()
        scores = dict(ranker.rank("ke toan", filler + [target]))
        self.assertIn("zzzzz-target", scores)
