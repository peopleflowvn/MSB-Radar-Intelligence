from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol

from .resolver import SourceSnapshot
from .validator import EvidenceValidationError


class RadarHttpClient(Protocol):
    def get(self, url: str, headers: Mapping[str, str], timeout_seconds: float) -> tuple[int, bytes]: ...


class UrllibRadarHttpClient:
    def get(self, url: str, headers: Mapping[str, str], timeout_seconds: float) -> tuple[int, bytes]:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise EvidenceValidationError("Radar evidence resolver unavailable") from exc


@dataclass(frozen=True)
class RadarResolverConfig:
    base_url: str
    service_token: str
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.base_url.lower().startswith("https://"):
            raise ValueError("Radar base_url must use HTTPS")
        if not self.service_token.strip():
            raise ValueError("Radar service_token must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class RadarHttpSourceResolver:
    """Client for the proposed Radar-owned evidence-resolution endpoint."""

    def __init__(self, config: RadarResolverConfig, client: RadarHttpClient | None = None) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._service_token = config.service_token
        self._timeout = config.timeout_seconds
        self._client = client or UrllibRadarHttpClient()

    def resolve(self, *, document_id: str, scope_token: str) -> SourceSnapshot | None:
        if not document_id.strip() or not scope_token.strip():
            raise EvidenceValidationError("document_id and scope_token are required")
        status, raw = self._client.get(
            f"{self._base_url}/api/v1/talent/intelligence/evidence/documents/{document_id}/",
            {
                "Authorization": f"Bearer {self._service_token}",
                "X-Radar-Scope-Token": scope_token,
                "Accept": "application/json",
            },
            self._timeout,
        )
        if status in {403, 404}:
            return None
        if status == 410:
            return SourceSnapshot(document_id, "deleted", "deleted", "deleted", exists=False)
        if status != 200:
            raise EvidenceValidationError(f"Radar evidence resolver HTTP {status}")
        try:
            payload = json.loads(raw.decode("utf-8"))
            snapshot = SourceSnapshot(
                document_id=str(payload["document_id"]),
                person_id=str(payload["person_id"]),
                version=str(payload["version"]),
                content_hash=str(payload["content_hash"]),
                exists=bool(payload.get("exists", True)),
            )
            if not all((snapshot.document_id.strip(), snapshot.person_id.strip(), snapshot.version.strip(), snapshot.content_hash.strip())):
                raise ValueError
            return snapshot
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EvidenceValidationError("Radar evidence resolver returned malformed data") from exc
