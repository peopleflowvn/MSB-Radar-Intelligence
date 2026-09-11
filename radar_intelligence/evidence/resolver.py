from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from radar_intelligence.contracts import Evidence

from .validator import EvidenceValidationError, validate_citations


@dataclass(frozen=True)
class SourceSnapshot:
    document_id: str
    person_id: str
    version: str
    content_hash: str
    exists: bool = True


class SourceResolver(Protocol):
    def resolve(self, *, document_id: str, scope_token: str) -> SourceSnapshot | None: ...


def resolve_citations(
    evidence: tuple[Evidence, ...],
    cited_ids: tuple[str, ...],
    *,
    allowed_person_ids: set[str],
    scope_token: str,
    resolver: SourceResolver,
) -> tuple[Evidence, ...]:
    if not scope_token.strip():
        raise EvidenceValidationError("scope_token must not be empty")
    validated = validate_citations(evidence, cited_ids, allowed_person_ids)
    snapshots: dict[str, SourceSnapshot | None] = {}
    for item in validated:
        if item.document_id not in snapshots:
            snapshots[item.document_id] = resolver.resolve(
                document_id=item.document_id,
                scope_token=scope_token,
            )
        current = snapshots[item.document_id]
        if current is None or not current.exists:
            raise EvidenceValidationError(f"source unavailable or unauthorized: {item.evidence_id}")
        if current.document_id != item.document_id or current.person_id != item.person_id:
            raise EvidenceValidationError(f"source identity mismatch: {item.evidence_id}")
        if current.version != item.document_version or current.content_hash != item.content_hash:
            raise EvidenceValidationError(f"stale evidence: {item.evidence_id}")
    return validated
