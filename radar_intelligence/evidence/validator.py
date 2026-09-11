from __future__ import annotations

from radar_intelligence.contracts import Evidence


class EvidenceValidationError(ValueError):
    pass


def validate_citations(
    evidence: tuple[Evidence, ...],
    cited_ids: tuple[str, ...],
    allowed_person_ids: set[str] | None = None,
) -> tuple[Evidence, ...]:
    by_id = {item.evidence_id: item for item in evidence}
    if len(by_id) != len(evidence):
        raise EvidenceValidationError("duplicate evidence_id")
    validated: list[Evidence] = []
    for evidence_id in cited_ids:
        item = by_id.get(evidence_id)
        if item is None:
            raise EvidenceValidationError(f"unknown evidence_id: {evidence_id}")
        if item.is_deleted:
            raise EvidenceValidationError(f"deleted evidence: {evidence_id}")
        if allowed_person_ids is not None and item.person_id not in allowed_person_ids:
            raise EvidenceValidationError(f"evidence outside allowed people: {evidence_id}")
        validated.append(item)
    return tuple(validated)

