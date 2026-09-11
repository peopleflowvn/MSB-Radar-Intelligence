from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DatasetContractError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    category: str
    query: str
    expected_path: str
    source: str
    relevant_person_ids: tuple[str, ...] | None = None

    @property
    def is_scored(self) -> bool:
        return self.relevant_person_ids is not None


@dataclass(frozen=True)
class EvaluationDataset:
    cases: tuple[EvaluationCase, ...]
    sha256: str

    @property
    def scored_cases(self) -> tuple[EvaluationCase, ...]:
        return tuple(case for case in self.cases if case.is_scored)


def load_jsonl_dataset(path: Path) -> EvaluationDataset:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetContractError("dataset must be UTF-8") from exc
    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetContractError(f"line {line_number}: invalid JSON") from exc
        case = _decode_case(value, line_number)
        if case.case_id in seen:
            raise DatasetContractError(f"line {line_number}: duplicate id {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise DatasetContractError("dataset must contain at least one case")
    return EvaluationDataset(tuple(cases), hashlib.sha256(raw).hexdigest())


def _decode_case(value: Any, line_number: int) -> EvaluationCase:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DatasetContractError(f"line {line_number}: case must be an object")
    required = {"id", "category", "query", "expected_path", "source"}
    allowed = required | {"relevant_person_ids"}
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise DatasetContractError(f"line {line_number}: missing fields: {', '.join(missing)}")
    if unknown:
        raise DatasetContractError(f"line {line_number}: unknown fields: {', '.join(unknown)}")
    strings: dict[str, str] = {}
    for name in required:
        item = value[name]
        if not isinstance(item, str) or not item.strip():
            raise DatasetContractError(f"line {line_number}: {name} must be a non-empty string")
        strings[name] = item.strip()
    relevant = value.get("relevant_person_ids")
    if relevant is not None:
        if not isinstance(relevant, list) or any(not isinstance(item, str) or not item.strip() for item in relevant):
            raise DatasetContractError(f"line {line_number}: relevant_person_ids must be an array of non-empty strings")
        if len(relevant) != len(set(relevant)):
            raise DatasetContractError(f"line {line_number}: relevant_person_ids contains duplicates")
        relevant = tuple(relevant)
    return EvaluationCase(
        case_id=strings["id"], category=strings["category"], query=strings["query"],
        expected_path=strings["expected_path"], source=strings["source"],
        relevant_person_ids=relevant,
    )
