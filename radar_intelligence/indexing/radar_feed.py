from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

from radar_intelligence.contracts import DocumentRef

from .core import ChangeOperation, DocumentChange


class FeedError(RuntimeError):
    pass


class FeedHttpClient(Protocol):
    def get(self, url: str, headers: Mapping[str, str], timeout_seconds: float) -> tuple[int, bytes]: ...


class UrllibFeedHttpClient:
    def get(self, url: str, headers: Mapping[str, str], timeout_seconds: float) -> tuple[int, bytes]:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.status, response.read()
        except Exception as exc:
            raise FeedError("Radar document feed unavailable") from exc


@dataclass(frozen=True)
class RadarFeedConfig:
    base_url: str
    service_token: str
    scope_token: str
    timeout_seconds: float = 15.0
    page_size: int = 100

    def __post_init__(self) -> None:
        normalized = self.base_url.rstrip("/").lower()
        if not (normalized.startswith("https://") or normalized == "http://hub:8000"):
            raise ValueError("Radar base_url must use HTTPS or the fixed Docker-internal Hub URL")
        if not self.service_token.strip() or not self.scope_token.strip():
            raise ValueError("service_token and scope_token are required")
        if self.timeout_seconds <= 0 or not 1 <= self.page_size <= 1000:
            raise ValueError("invalid feed timeout or page_size")


@dataclass(frozen=True)
class FeedPage:
    events: tuple[DocumentChange, ...]
    next_cursor: str | None
    has_more: bool


class RadarDocumentFeedClient:
    """Client for a proposed ordered, replayable Radar document-change feed."""

    def __init__(self, config: RadarFeedConfig, client: FeedHttpClient | None = None) -> None:
        self._config = config
        self._client = client or UrllibFeedHttpClient()

    def fetch(self, cursor: str | None = None) -> FeedPage:
        query = {"limit": str(self._config.page_size)}
        if cursor:
            query["cursor"] = cursor
        url = (
            self._config.base_url.rstrip("/")
            + "/api/v1/talent/intelligence/document-feed/?"
            + urllib.parse.urlencode(query)
        )
        status, raw = self._client.get(url, {
            "Authorization": f"Bearer {self._config.service_token}",
            "X-Radar-Scope-Token": self._config.scope_token,
            "Accept": "application/json",
        }, self._config.timeout_seconds)
        if status != 200:
            raise FeedError(f"Radar document feed HTTP {status}")
        try:
            payload = json.loads(raw.decode("utf-8"))
            events = tuple(_parse_event(row) for row in payload["events"])
            next_cursor = payload.get("next_cursor")
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise ValueError
            has_more = bool(payload.get("has_more", False))
            if has_more and not next_cursor:
                raise ValueError
            if events and not next_cursor:
                raise ValueError
            return FeedPage(events, next_cursor, has_more)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FeedError("Radar document feed returned malformed data") from exc


def _parse_event(row: Mapping[str, object]) -> DocumentChange:
    operation = ChangeOperation(str(row["operation"]))
    updated_at = datetime.fromisoformat(str(row["updated_at"]).replace("Z", "+00:00"))
    document = DocumentRef(
        document_id=str(row["document_id"]),
        person_id=str(row["person_id"]),
        version=str(row["version"]),
        content_hash=str(row["content_hash"]),
        source_record_id=str(row["source_record_id"]) if row.get("source_record_id") is not None else None,
    )
    return DocumentChange(
        event_id=str(row["event_id"]),
        operation=operation,
        document=document,
        updated_at=updated_at,
        source=str(row["source"]),
        document_type=str(row["document_type"]),
        text=str(row["text"]) if row.get("text") is not None else None,
        document_date=(datetime.fromisoformat(str(row["document_date"]).replace("Z", "+00:00"))
                       if row.get("document_date") else None),
        application_id=str(row["application_id"]) if row.get("application_id") is not None else None,
    )
