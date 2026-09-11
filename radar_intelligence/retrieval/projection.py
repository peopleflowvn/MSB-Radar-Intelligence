from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from radar_intelligence.contracts import Evidence, PersonRef
from radar_intelligence.indexing import SearchDocument

from .engine import RetrievalRecord
from .hybrid import CandidateChunk


class ProjectionError(ValueError):
    pass


def project_search_documents(
    documents: Sequence[SearchDocument],
    *,
    person_labels: Mapping[str, str] | None = None,
) -> tuple[RetrievalRecord, ...]:
    """Project disposable index chunks into public retrieval records.

    Radar identity and document-version fields are required. Optional structured
    fields are accepted only with explicit types; malformed index metadata fails
    closed instead of weakening a filter.
    """
    labels = person_labels or {}
    return tuple(_project(document, labels) for document in documents)


def _required_text(metadata: Mapping[str, Any], name: str) -> str:
    value = metadata.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ProjectionError(f"index metadata {name} must be a non-empty string")
    return value.strip()


def _text_tuple(metadata: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = metadata.get(name, ())
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ProjectionError(f"index metadata {name} must be an array of strings")
    return tuple(item for item in value if item.strip())


def _project(document: SearchDocument, labels: Mapping[str, str]) -> RetrievalRecord:
    metadata = document.metadata
    person_id = _required_text(metadata, "person_id")
    document_id = _required_text(metadata, "document_id")
    source = _required_text(metadata, "source")
    content_hash = _required_text(metadata, "content_hash")
    version = _required_text(metadata, "version")
    chunk_id = _required_text(metadata, "chunk_id")
    if chunk_id != document.chunk_id:
        raise ProjectionError("index metadata chunk_id does not match the document")
    position = metadata.get("chunk_position")
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        raise ProjectionError("index metadata chunk_position must be a non-negative integer")
    years = metadata.get("years_experience")
    if years is not None and (isinstance(years, bool) or not isinstance(years, (int, float)) or years < 0):
        raise ProjectionError("index metadata years_experience must be a non-negative number")
    evidence = Evidence(
        evidence_id=chunk_id,
        person_id=person_id,
        document_id=document_id,
        source=source,
        text=document.content,
        location=f"chunk {position}",
        score=1.0,
        content_hash=content_hash,
        document_version=version,
    )
    return RetrievalRecord(
        chunk=CandidateChunk(PersonRef(person_id, labels.get(person_id)), evidence),
        locations=_text_tuple(metadata, "locations"),
        skills=_text_tuple(metadata, "skills"),
        companies=_text_tuple(metadata, "companies"),
        education=_text_tuple(metadata, "education"),
        years_experience=float(years) if years is not None else None,
        embedding=document.embedding,
    )
