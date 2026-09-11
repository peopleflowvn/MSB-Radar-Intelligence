from __future__ import annotations

import unittest

from radar_intelligence.contracts import Evidence, PersonRef
from radar_intelligence.retrieval import CandidateChunk, group_and_fuse


def chunk(person_id: str, evidence_id: str, lexical: int | None, semantic: int | None) -> CandidateChunk:
    person = PersonRef(person_id)
    evidence = Evidence(evidence_id, person_id, "d-" + evidence_id, "cv", "text", "page 1", 0.8, "sha", "1")
    return CandidateChunk(person, evidence, lexical, semantic)


class RetrievalTest(unittest.TestCase):
    def test_results_are_grouped_by_person(self) -> None:
        hits = group_and_fuse([
            chunk("p1", "e1", 1, 2),
            chunk("p1", "e2", 2, 1),
            chunk("p2", "e3", 3, 3),
        ])
        self.assertEqual([hit.person.person_id for hit in hits], ["p1", "p2"])
        self.assertEqual(len(hits[0].evidence), 2)

    def test_wrong_person_chunk_is_rejected(self) -> None:
        item = chunk("p1", "e1", 1, 1)
        bad = CandidateChunk(PersonRef("p2"), item.evidence, 1, 1)
        with self.assertRaises(ValueError):
            group_and_fuse([bad])


if __name__ == "__main__":
    unittest.main()
