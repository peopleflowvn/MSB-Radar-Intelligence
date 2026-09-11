from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol


class Capability(str, Enum):
    FAST = "fast"
    DEEP = "deep"
    VISION = "vision"
    EMBEDDING = "embedding"


@dataclass(frozen=True)
class GatewayRequest:
    capability: Capability
    input_text: str
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class GatewayResponse:
    output_text: str
    provider: str
    model_alias: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str | None = None


class Transport(Protocol):
    def complete(self, *, model: str, text: str, timeout_seconds: float) -> GatewayResponse: ...


class ModelGateway:
    def __init__(self, routes: Mapping[Capability, str], transport: Transport) -> None:
        missing = set(Capability) - set(routes)
        if missing:
            raise ValueError(f"missing capability routes: {sorted(item.value for item in missing)}")
        self._routes = dict(routes)
        self._transport = transport

    def complete(self, request: GatewayRequest) -> GatewayResponse:
        if not request.input_text.strip():
            raise ValueError("input_text must not be empty")
        if request.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        return self._transport.complete(
            model=self._routes[request.capability],
            text=request.input_text,
            timeout_seconds=request.timeout_seconds,
        )
