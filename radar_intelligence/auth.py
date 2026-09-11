from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol


class ScopeValidationError(RuntimeError):
    pass


class ScopeHttpClient(Protocol):
    def post(self, url: str, headers: Mapping[str, str], timeout_seconds: float) -> tuple[int, bytes]: ...


class UrllibScopeHttpClient:
    def post(self, url: str, headers: Mapping[str, str], timeout_seconds: float) -> tuple[int, bytes]:
        request = urllib.request.Request(url, data=b"", headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ScopeValidationError("Radar scope validator unavailable") from exc


@dataclass(frozen=True)
class RadarScopeConfig:
    base_url: str
    service_token: str
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.base_url.lower().startswith("https://"):
            raise ValueError("Radar base_url must use HTTPS")
        if not self.service_token.strip() or self.timeout_seconds <= 0:
            raise ValueError("service token and positive timeout are required")


class RadarScopeValidator:
    def __init__(self, config: RadarScopeConfig, client: ScopeHttpClient | None = None) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._token = config.service_token
        self._timeout = config.timeout_seconds
        self._client = client or UrllibScopeHttpClient()

    def validate(self, scope_token: str) -> bool:
        if not scope_token.strip():
            return False
        status, raw = self._client.post(
            self._base_url + "/api/v1/talent/intelligence/scope/validate/",
            {"Authorization": f"Bearer {self._token}",
             "X-Radar-Scope-Token": scope_token, "Accept": "application/json"},
            self._timeout,
        )
        if status in {403, 404}:
            return False
        if status != 200:
            raise ScopeValidationError(f"Radar scope validator HTTP {status}")
        try:
            payload = json.loads(raw.decode("utf-8"))
            return payload == {"allowed": True, "scope": "all_applicants"}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
