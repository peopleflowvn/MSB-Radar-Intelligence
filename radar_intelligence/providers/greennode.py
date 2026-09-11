from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol

from .gateway import GatewayResponse


class ProviderError(RuntimeError):
    pass


class HttpClient(Protocol):
    def post(self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float) -> bytes: ...


class UrllibHttpClient:
    def post(self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float) -> bytes:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"GreenNode HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = "timeout" if "timed out" in str(exc).lower() else "transport unavailable"
            raise ProviderError(f"GreenNode {reason}") from exc


@dataclass(frozen=True)
class GreenNodeConfig:
    base_url: str
    api_key: str

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("GreenNode base_url must not be empty")
        if not self.api_key.strip():
            raise ValueError("GreenNode api_key must not be empty")
        if not self.base_url.lower().startswith("https://"):
            raise ValueError("GreenNode base_url must use HTTPS")


class GreenNodeTransport:
    """Small OpenAI-compatible chat transport for capability-selected models."""

    def __init__(self, config: GreenNodeConfig, http_client: HttpClient | None = None) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._api_key = config.api_key
        self._http = http_client or UrllibHttpClient()

    def complete(self, *, model: str, text: str, timeout_seconds: float) -> GatewayResponse:
        if not model.strip():
            raise ValueError("model alias must not be empty")
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": text}],
            "stream": False,
        }
        raw = self._http.post(
            self._base_url + "/chat/completions",
            {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout_seconds,
        )
        try:
            response = json.loads(raw.decode("utf-8"))
            output = response["choices"][0]["message"]["content"]
            if not isinstance(output, str) or not output.strip():
                raise ValueError
            usage = response.get("usage") or {}
            return GatewayResponse(
                output_text=output,
                provider="greennode",
                model_alias=model,
                input_tokens=_optional_int(usage.get("prompt_tokens")),
                output_tokens=_optional_int(usage.get("completion_tokens")),
                request_id=str(response["id"]) if response.get("id") else None,
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("GreenNode returned a malformed chat completion") from exc


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid token usage") from exc
    return parsed if parsed >= 0 else None
