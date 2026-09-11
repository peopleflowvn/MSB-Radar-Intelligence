from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class TraceError:
    code: str
    dependency: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required(self.code, "code"))
        if self.dependency is not None:
            object.__setattr__(self, "dependency", _required(self.dependency, "dependency"))


@dataclass(frozen=True)
class OperationalTrace:
    request_id: str
    execution_class: str
    status: str
    thread_id: str | None = None
    tools: tuple[str, ...] = ()
    retrieval_path: tuple[str, ...] = ()
    candidate_count: int = 0
    evidence_count: int = 0
    provider: str | None = None
    model_alias: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0
    fallback: str | None = None
    errors: tuple[TraceError, ...] = ()

    def __post_init__(self) -> None:
        for name in ("request_id", "execution_class", "status"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        for name in ("candidate_count", "evidence_count", "latency_ms"):
            _non_negative(getattr(self, name), name)
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value is not None:
                _non_negative(value, name)
        for name in ("thread_id", "provider", "model_alias", "fallback"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _required(value, name))
        for name in ("tools", "retrieval_path"):
            values = getattr(self, name)
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{name} must contain non-empty strings")

    def to_safe_dict(self) -> dict[str, Any]:
        """Return an allow-listed record with no query, evidence text, token or reasoning."""
        return {
            "request_id": self.request_id,
            "thread_id": self.thread_id,
            "execution_class": self.execution_class,
            "status": self.status,
            "tools": list(self.tools),
            "retrieval_path": list(self.retrieval_path),
            "candidate_count": self.candidate_count,
            "evidence_count": self.evidence_count,
            "provider": self.provider,
            "model_alias": self.model_alias,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "fallback": self.fallback,
            "errors": [
                {"code": error.code, "dependency": error.dependency, "retryable": error.retryable}
                for error in self.errors
            ],
        }
