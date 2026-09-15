from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from radar_intelligence.contracts import (
    AnswerRequest, AnswerResponse, Evidence, ModelTrace, PersonRef,
    SearchFilters, SearchHit, SearchRequest,
)


class ApiContractError(ValueError):
    """Safe validation error for data crossing the public JSON boundary."""


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ApiContractError(f"{path} must be an object")
    return value


def _fields(value: Mapping[str, Any], allowed: set[str], required: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        raise ApiContractError(f"{path} contains unknown fields: {', '.join(unknown)}")
    if missing:
        raise ApiContractError(f"{path} is missing fields: {', '.join(missing)}")


def _string(value: Any, path: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ApiContractError(f"{path} must be a string")
    return value


def _strings(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ApiContractError(f"{path} must be an array of strings")
    return tuple(value)


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiContractError(f"{path} must be a number")
    return float(value)


def decode_search_request(payload: Any) -> SearchRequest:
    data = _object(payload, "request")
    allowed = {"query", "scope_token", "principal_id", "filters", "limit", "thread_id",
               "person_ids", "knowledge_ids", "knowledge_only"}
    _fields(data, allowed, {"query", "scope_token", "principal_id"}, "request")
    filters = _decode_filters(data.get("filters", {}))
    limit = data.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ApiContractError("request.limit must be an integer")
    knowledge_only = data.get("knowledge_only", False)
    if not isinstance(knowledge_only, bool):
        raise ApiContractError("request.knowledge_only must be a boolean")
    try:
        return SearchRequest(
            query=_string(data["query"], "request.query") or "",
            scope_token=_string(data["scope_token"], "request.scope_token") or "",
            principal_id=_string(data["principal_id"], "request.principal_id") or "",
            filters=filters,
            limit=limit,
            thread_id=_string(data.get("thread_id"), "request.thread_id", optional=True),
            person_ids=_strings(data.get("person_ids", []), "request.person_ids"),
            knowledge_ids=_strings(data.get("knowledge_ids", []), "request.knowledge_ids"),
            knowledge_only=knowledge_only,
        )
    except ValueError as exc:
        raise ApiContractError(str(exc)) from None


def _decode_filters(payload: Any) -> SearchFilters:
    data = _object(payload, "request.filters")
    allowed = {
        "locations", "skills_all", "companies", "education",
        "min_years_experience", "max_years_experience", "excluded_terms",
    }
    _fields(data, allowed, set(), "request.filters")

    def optional_number(name: str) -> float | None:
        value = data.get(name)
        return None if value is None else _number(value, f"request.filters.{name}")

    try:
        return SearchFilters(
            locations=_strings(data.get("locations", []), "request.filters.locations"),
            skills_all=_strings(data.get("skills_all", []), "request.filters.skills_all"),
            companies=_strings(data.get("companies", []), "request.filters.companies"),
            education=_strings(data.get("education", []), "request.filters.education"),
            min_years_experience=optional_number("min_years_experience"),
            max_years_experience=optional_number("max_years_experience"),
            excluded_terms=_strings(data.get("excluded_terms", []), "request.filters.excluded_terms"),
        )
    except ValueError as exc:
        raise ApiContractError(str(exc)) from None


def decode_answer_request(payload: Any) -> AnswerRequest:
    data = _object(payload, "request")
    allowed = {"question", "scope_token", "principal_id", "thread_id", "person_ids", "knowledge_ids"}
    _fields(data, allowed, {"question", "scope_token", "principal_id"}, "request")
    try:
        return AnswerRequest(
            question=_string(data["question"], "request.question") or "",
            scope_token=_string(data["scope_token"], "request.scope_token") or "",
            principal_id=_string(data["principal_id"], "request.principal_id") or "",
            thread_id=_string(data.get("thread_id"), "request.thread_id", optional=True),
            person_ids=_strings(data.get("person_ids", []), "request.person_ids"),
            knowledge_ids=_strings(data.get("knowledge_ids", []), "request.knowledge_ids"),
        )
    except ValueError as exc:
        raise ApiContractError(str(exc)) from None


def encode_search_hit(hit: SearchHit) -> dict[str, Any]:
    return {
        "person": _encode_person(hit.person), "score": hit.score,
        "evidence": [_encode_evidence(item) for item in hit.evidence],
        "matched_filters": list(hit.matched_filters),
    }


def encode_answer_response(response: AnswerResponse) -> dict[str, Any]:
    return {
        "answer": response.answer,
        "people": [_encode_person(item) for item in response.people],
        "evidence": [_encode_evidence(item) for item in response.evidence],
        "cited_evidence_ids": list(response.cited_evidence_ids),
        "interpreted_query": _json_value(response.interpreted_query, "interpreted_query"),
        "trace": [_encode_trace(item) for item in response.trace],
    }


def _encode_person(person: PersonRef) -> dict[str, Any]:
    return {"person_id": person.person_id, "display_name": person.display_name}


def _encode_evidence(item: Evidence) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id, "person_id": item.person_id,
        "document_id": item.document_id, "source": item.source, "text": item.text,
        "location": item.location, "score": item.score, "content_hash": item.content_hash,
        "document_version": item.document_version, "is_deleted": item.is_deleted,
    }


def _encode_trace(item: ModelTrace) -> dict[str, Any]:
    return {
        "capability": item.capability, "provider": item.provider,
        "model_alias": item.model_alias, "latency_ms": item.latency_ms,
        "input_tokens": item.input_tokens, "output_tokens": item.output_tokens,
        "request_id": item.request_id,
    }


def _json_value(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ApiContractError(f"{path} object keys must be strings")
        return {key: _json_value(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item, path) for item in value]
    raise ApiContractError(f"{path} contains a non-JSON value")
