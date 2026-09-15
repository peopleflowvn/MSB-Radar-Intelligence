from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import time

from radar_intelligence.config import RuntimeSettings
from radar_intelligence.providers import (
    GreenNodeConfig, GreenNodeEmbedder, ProviderError, UrllibHttpClient,
)

from .coordinator import IndexSyncCoordinator, SqliteCursorStore
from .core import IncrementalIndexer
from .radar_feed import RadarDocumentFeedClient, RadarFeedConfig
from .sqlite_store import SqliteDocumentIndex


class _PacedEmbedder:
    """Keep the background synchronizer below a provider's sustained rate limit."""

    def __init__(self, delegate, minimum_interval_seconds: float) -> None:
        self._delegate = delegate
        self._minimum_interval_seconds = minimum_interval_seconds
        self._last_call = 0.0

    def embed_documents(self, texts):
        delay = self._minimum_interval_seconds - (time.monotonic() - self._last_call)
        if delay > 0:
            time.sleep(delay)
        try:
            return self._delegate.embed_documents(texts)
        finally:
            self._last_call = time.monotonic()


class _ProviderFallbackIndexer:
    """Persist lexical chunks when the remote embedding service is unavailable."""

    def __init__(self, primary, lexical) -> None:
        self._primary = primary
        self._lexical = lexical
        self._provider_available = True

    def apply(self, change):
        if not self._provider_available:
            return self._lexical.apply(change)
        try:
            return self._primary.apply(change)
        except ProviderError:
            # A provider outage or quota limit normally affects the whole sync
            # batch. Trip the process-local circuit breaker so the remaining
            # authorized documents become searchable immediately instead of
            # repeatedly waiting for a remote request that cannot succeed.
            self._provider_available = False
            return self._lexical.apply(change)


def _positive_number(name: str, default: str, cast):
    try:
        value = cast(os.environ.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


_KNOWLEDGE_FEED_PATH = "/api/v1/talent/intelligence/knowledge-feed/"
_KNOWLEDGE_CURSOR_NAMESPACE = "radar-knowledge-feed"


def build_coordinator(
    settings: RuntimeSettings,
    *,
    feed_path: str | None = None,
    cursor_namespace: str = "radar-document-feed",
) -> IndexSyncCoordinator:
    if not settings.ready:
        raise ValueError("runtime settings incomplete: " + ",".join(settings.missing))
    values = settings.values
    database = Path(os.environ.get(
        "INTELLIGENCE_INDEX_DB", "/var/lib/radar-intelligence/index.sqlite3"))
    feed_config_kwargs = {"path": feed_path} if feed_path else {}
    feed = RadarDocumentFeedClient(RadarFeedConfig(
        base_url=values["RADAR_BASE_URL"],
        service_token=values["RADAR_SERVICE_TOKEN"],
        scope_token=values["RADAR_INDEX_SCOPE_TOKEN"],
        timeout_seconds=_positive_number("INTELLIGENCE_FEED_TIMEOUT_SECONDS", "30", float),
        page_size=_positive_number("INTELLIGENCE_FEED_PAGE_SIZE", "100", int),
        **feed_config_kwargs,
    ))
    allow_lexical_fallback = os.environ.get(
        "INTELLIGENCE_ALLOW_LEXICAL_FALLBACK", "1").lower() in {"1", "true", "yes"}
    embedder = GreenNodeEmbedder(
        GreenNodeConfig(values["GREENNODE_BASE_URL"], values["GREENNODE_API_KEY"]),
        values["GREENNODE_MODEL_EMBEDDING"],
        http_client=UrllibHttpClient(retry_attempts=1 if allow_lexical_fallback else 4),
    )
    # The default is intentionally conservative. A value of zero is useful only
    # for controlled local tests and is rejected in production configuration.
    minimum_interval = _positive_number(
        "INTELLIGENCE_EMBEDDING_MIN_INTERVAL_SECONDS", "5", float)
    store = SqliteDocumentIndex(database)
    primary = IncrementalIndexer(
            store,
            embedder=_PacedEmbedder(embedder, minimum_interval),
            embedding_batch_size=_positive_number("INTELLIGENCE_EMBEDDING_BATCH_SIZE", "1", int),
        )
    indexer = (_ProviderFallbackIndexer(primary, IncrementalIndexer(store))
               if allow_lexical_fallback else primary)
    return IndexSyncCoordinator(
        feed,
        indexer,
        SqliteCursorStore(database, namespace=cursor_namespace),
    )


def _run_and_report(coordinator: IndexSyncCoordinator, *, max_pages: int, event: str, one_shot: bool) -> None:
    try:
        report = coordinator.run(max_pages=max_pages)
        print(json.dumps({"event": event, **report.__dict__}, default=str), flush=True)
    except Exception as exc:
        # Deliberately log only the error type/message from the bounded
        # bridge; document text is never included.
        print(json.dumps({
            "event": f"{event}_failed", "error_type": type(exc).__name__,
            "detail": str(exc),
        }), file=sys.stderr, flush=True)
        if one_shot:
            raise


def main() -> None:
    settings = RuntimeSettings.from_env()
    coordinator = build_coordinator(settings)
    # A second, independent feed for internal-knowledge documents (policies,
    # procedures) — same store, same search index, but its own cursor so an
    # outage or backlog on one feed never blocks the other. Off by default
    # requires nothing extra: an empty/absent knowledge-feed response is a
    # normal empty page, not an error.
    knowledge_enabled = os.environ.get(
        "INTELLIGENCE_KNOWLEDGE_FEED_ENABLED", "1").lower() in {"1", "true", "yes"}
    knowledge_coordinator = build_coordinator(
        settings, feed_path=_KNOWLEDGE_FEED_PATH, cursor_namespace=_KNOWLEDGE_CURSOR_NAMESPACE,
    ) if knowledge_enabled else None
    interval = _positive_number("INTELLIGENCE_SYNC_INTERVAL_SECONDS", "30", float)
    max_pages = _positive_number("INTELLIGENCE_SYNC_MAX_PAGES", "100", int)
    one_shot = os.environ.get("INTELLIGENCE_SYNC_ONCE", "").lower() in {"1", "true", "yes"}
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        _run_and_report(coordinator, max_pages=max_pages, event="index_sync", one_shot=one_shot)
        if knowledge_coordinator is not None:
            _run_and_report(
                knowledge_coordinator, max_pages=max_pages,
                event="knowledge_index_sync", one_shot=one_shot)
        if one_shot:
            return
        deadline = time.monotonic() + interval
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
