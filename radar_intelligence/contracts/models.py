from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


def _required(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


@dataclass(frozen=True)
class PersonRef:
    person_id: str
    display_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "person_id", _required(self.person_id, "person_id"))


@dataclass(frozen=True)
class DocumentRef:
    document_id: str
    person_id: str
    version: str
    content_hash: str
    source_record_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("document_id", "person_id", "version", "content_hash"):
            object.__setattr__(self, name, _required(getattr(self, name), name))


@dataclass(frozen=True)
class SearchFilters:
    locations: tuple[str, ...] = ()
    skills_all: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()
    education: tuple[str, ...] = ()
    min_years_experience: float | None = None
    max_years_experience: float | None = None
    excluded_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.min_years_experience is not None and self.min_years_experience < 0:
            raise ValueError("min_years_experience must be non-negative")
        if self.max_years_experience is not None and self.max_years_experience < 0:
            raise ValueError("max_years_experience must be non-negative")
        if (
            self.min_years_experience is not None
            and self.max_years_experience is not None
            and self.min_years_experience > self.max_years_experience
        ):
            raise ValueError("minimum experience cannot exceed maximum")


@dataclass(frozen=True)
class SearchRequest:
    query: str
    scope_token: str
    principal_id: str
    filters: SearchFilters = field(default_factory=SearchFilters)
    limit: int = 10
    thread_id: str | None = None
    # Empty = search the caller's whole authorized candidate corpus (today's
    # behavior, unchanged for every existing caller). Non-empty narrows that
    # corpus to exactly these person_ids for this request.
    person_ids: tuple[str, ...] = ()
    # Explicit opt-in allowlist for non-candidate records (person_id starting
    # with "-", e.g. an internal-knowledge document indexed as its own
    # negative-id "person"). Unlike `person_ids`, empty here means NONE are
    # included — a caller must name exactly which ones this request's role is
    # authorized for. Kept separate from `person_ids` because the two need
    # opposite empty-set defaults: "no candidate restriction" cannot also mean
    # "every non-candidate record is open to everyone".
    knowledge_ids: tuple[str, ...] = ()
    # Drop candidate records entirely and search only the allowed knowledge_ids.
    # Needed when the result is injected as context into a general conversation
    # prompt: a CV that happens to mention "quy trình nghỉ phép" must not be
    # read back as if it were the company's leave policy.
    knowledge_only: bool = False

    def __post_init__(self) -> None:
        for name in ("query", "scope_token", "principal_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    person_id: str
    document_id: str
    source: str
    text: str
    location: str
    score: float
    content_hash: str
    document_version: str
    is_deleted: bool = False

    def __post_init__(self) -> None:
        for name in (
            "evidence_id", "person_id", "document_id", "source", "text",
            "location", "content_hash", "document_version",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not 0 <= self.score <= 1:
            raise ValueError("evidence score must be between 0 and 1")


@dataclass(frozen=True)
class SearchHit:
    person: PersonRef
    score: float
    evidence: tuple[Evidence, ...]
    matched_filters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 1:
            raise ValueError("search score must be between 0 and 1")
        if any(item.person_id != self.person.person_id for item in self.evidence):
            raise ValueError("all evidence must belong to the hit person")


@dataclass(frozen=True)
class AnswerRequest:
    question: str
    scope_token: str
    principal_id: str
    thread_id: str | None = None
    person_ids: tuple[str, ...] = ()
    # See SearchRequest.knowledge_ids: same opt-in-only semantics.
    knowledge_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("question", "scope_token", "principal_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))


@dataclass(frozen=True)
class ModelTrace:
    capability: str
    provider: str
    model_alias: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class AnswerResponse:
    answer: str
    people: tuple[PersonRef, ...]
    evidence: tuple[Evidence, ...]
    cited_evidence_ids: tuple[str, ...]
    interpreted_query: Mapping[str, Any]
    trace: tuple[ModelTrace, ...] = ()


@dataclass(frozen=True)
class ThreadState:
    thread_id: str
    principal_id: str
    scope_fingerprint: str
    referenced_people: tuple[str, ...] = ()
    referenced_evidence: tuple[str, ...] = ()
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ActionStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


@dataclass(frozen=True)
class AgentAction:
    action_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    status: ActionStatus = ActionStatus.PROPOSED
    consequential: bool = True
    approved_by: str | None = None

    def __post_init__(self) -> None:
        if self.consequential and self.status in {ActionStatus.APPROVED, ActionStatus.EXECUTED}:
            _required(self.approved_by or "", "approved_by")
