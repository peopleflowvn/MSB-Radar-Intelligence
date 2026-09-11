import unittest

from radar_intelligence.contracts import Evidence
from radar_intelligence.evidence import EvidenceValidationError, validate_citations


def evidence(evidence_id: str, person_id: str = "p1", deleted: bool = False) -> Evidence:
    return Evidence(evidence_id, person_id, "d1", "cv", "SQL at Bank A", "page 1", 0.9, "sha", "1", deleted)


class EvidenceTest(unittest.TestCase):
    def test_model_cannot_invent_citation(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            validate_citations((evidence("e1"),), ("e2",))

    def test_deleted_evidence_is_rejected(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            validate_citations((evidence("e1", deleted=True),), ("e1",))

    def test_wrong_person_evidence_is_rejected(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            validate_citations((evidence("e1", "p2"),), ("e1",), {"p1"})


if __name__ == "__main__":
    unittest.main()

