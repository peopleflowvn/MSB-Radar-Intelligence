from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
    # Preserve first-seen order so a fixed document is always the one whose
    # resolver error (if any) surfaces first, matching sequential behavior.
    document_ids = tuple(dict.fromkeys(item.document_id for item in validated))
    snapshots: dict[str, SourceSnapshot | None] = {}
    if len(document_ids) <= 1:
        for document_id in document_ids:
            snapshots[document_id] = resolver.resolve(document_id=document_id, scope_token=scope_token)
    else:
        # A grounded answer commonly cites several people/documents at once;
        # each resolve() is an independent Radar round-trip, so resolving them
        # concurrently turns N sequential network waits into one.
        with ThreadPoolExecutor(max_workers=min(8, len(document_ids))) as pool:
            futures = {
                document_id: pool.submit(resolver.resolve, document_id=document_id, scope_token=scope_token)
                for document_id in document_ids
            }
            for document_id, future in futures.items():
                snapshots[document_id] = future.result()
    for item in validated:
        current = snapshots[item.document_id]
        if current is None or not current.exists:
            raise EvidenceValidationError(f"source unavailable or unauthorized: {item.evidence_id}")
        if current.document_id != item.document_id or current.person_id != item.person_id:
            raise EvidenceValidationError(f"source identity mismatch: {item.evidence_id}")
        if current.version != item.document_version or current.content_hash != item.content_hash:
            raise EvidenceValidationError(f"stale evidence: {item.evidence_id}")
    return validated
