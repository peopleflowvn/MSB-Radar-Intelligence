from __future__ import annotations

import unittest

from radar_intelligence.contracts import Evidence, PersonRef, SearchFilters, SearchRequest
from radar_intelligence.retrieval import CandidateChunk, CosineSemanticRanker, HybridRetriever, RetrievalRecord, RetrievalScope, normalize_text


def record(person_id, evidence_id, text, **metadata):
    person = PersonRef(person_id, metadata.pop("display_name", person_id))
    evidence = Evidence(evidence_id, person_id, "d-" + evidence_id, "cv", text, "page 1", 0.8, "sha", "1")
    return RetrievalRecord(CandidateChunk(person, evidence), **metadata)


class RecordingSemanticRanker:
    def __init__(self, scores):
        self.scores = scores
        self.seen_people = []

    def rank(self, query, records):
        self.seen_people = [record.chunk.person.person_id for record in records]
        return [(record.chunk.evidence.evidence_id, self.scores.get(record.chunk.evidence.evidence_id, 0.0)) for record in records]


class RetrievalEngineTest(unittest.TestCase):
    def test_vietnamese_normalization(self):
        self.assertEqual(normalize_text("TP. Hồ Chí Minh – Đầu tư"), "tp ho chi minh dau tu")

    def test_structured_filters_are_hard_constraints(self):
        records = [
            record("p1", "e1", "SQL Python", locations=("Hà Nội",), skills=("SQL", "Python"), years_experience=6),
            record("p2", "e2", "SQL Python", locations=("Đà Nẵng",), skills=("SQL", "Python"), years_experience=7),
        ]
        request = SearchRequest("SQL", "scope", "u1", SearchFilters(locations=("Ha Noi",), min_years_experience=5))
        hits = HybridRetriever().search(request, records, RetrievalScope(frozenset({"p1", "p2"})))
        self.assertEqual([hit.person.person_id for hit in hits], ["p1"])

    def test_all_skills_and_exclusion_are_enforced(self):
        records = [
            record("p1", "e1", "Data at Bank A", skills=("SQL", "Python"), companies=("Bank A",)),
            record("p2", "e2", "Data at Insurance X", skills=("SQL",), companies=("Insurance X",)),
        ]
        filters = SearchFilters(skills_all=("SQL", "Python"), excluded_terms=("Insurance",))
        hits = HybridRetriever().search(SearchRequest("Data", "scope", "u1", filters), records, RetrievalScope(frozenset({"p1", "p2"})))
        self.assertEqual([hit.person.person_id for hit in hits], ["p1"])

    def test_empty_exclusions_do_not_normalize_every_evidence(self):
        class UnstringableCompanies(tuple):
            def __iter__(self):
                raise AssertionError("companies must not be scanned without exclusions")

        item = record("p1", "e1", "SQL", companies=UnstringableCompanies())
        hits = HybridRetriever().search(
            SearchRequest("SQL", "scope", "u1"), [item], RetrievalScope(frozenset({"p1"})))
        self.assertEqual([hit.person.person_id for hit in hits], ["p1"])

    def test_scope_is_applied_before_semantic_ranker(self):
        ranker = RecordingSemanticRanker({"e1": 0.8, "secret": 1.0})
        records = [record("p1", "e1", "risk"), record("p-secret", "secret", "risk")]
        hits = HybridRetriever(ranker).search(
            SearchRequest("risk", "scope", "u1"), records, RetrievalScope(frozenset({"p1"}))
        )
        self.assertEqual(ranker.seen_people, ["p1"])
        self.assertEqual([hit.person.person_id for hit in hits], ["p1"])

    def test_semantic_ranker_cannot_inject_unauthorized_evidence(self):
        class MaliciousRanker:
            def rank(self, query, records):
                return [("secret", 1.0)]

        with self.assertRaises(ValueError):
            HybridRetriever(MaliciousRanker()).search(
                SearchRequest("risk", "scope", "u1"),
                [record("p1", "e1", "risk")],
                RetrievalScope(frozenset({"p1"})),
            )

    def test_cosine_semantic_ranker_orders_by_query_similarity(self):
        class Embedder:
            def embed_documents(self, texts):
                return [(1.0, 0.0)]

        records = [
            record("p1", "e1", "unrelated", embedding=(0.0, 1.0)),
            record("p2", "e2", "also unrelated", embedding=(0.9, 0.1)),
        ]
        hits = HybridRetriever(CosineSemanticRanker(Embedder())).search(
            SearchRequest("leadership", "scope", "u1"), records, RetrievalScope(frozenset({"p1", "p2"}))
        )
        self.assertEqual([hit.person.person_id for hit in hits], ["p2", "p1"])

    def test_cosine_semantic_ranker_reuses_prepared_matrix(self):
        class Embedder:
            def embed_documents(self, texts):
                return [(1.0, 0.0)]

        records = [
            record("p1", "e1", "one", embedding=(1.0, 0.0)),
            record("p2", "e2", "two", embedding=(0.0, 1.0)),
        ]
        ranker = CosineSemanticRanker(Embedder())
        ranker.prepare(records)
        prepared = ranker._prepared_matrix
        ranker.rank("query", records)
        self.assertIs(ranker._prepared_matrix, prepared)

    def test_cosine_semantic_ranker_bounds_candidates(self):
        class Embedder:
            def embed_documents(self, texts):
                return [(1.0, 0.0)]

        records = [
            record("p1", "e1", "one", embedding=(1.0, 0.0)),
            record("p2", "e2", "two", embedding=(0.5, 0.5)),
        ]
        scores = CosineSemanticRanker(Embedder(), candidate_limit=1).rank("query", records)
        self.assertEqual([identifier for identifier, _ in scores], ["e1"])


if __name__ == "__main__":
    unittest.main()
