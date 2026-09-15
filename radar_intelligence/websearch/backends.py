from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

_DEFAULT_TIMEOUT = 12.0
_DEFAULT_ORDER = ("searxng", "duckduckgo", "tavily", "brave", "google_cse", "gemini_grounding")
_USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0 Safari/537.36")
_GEMINI_REST = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class WebSearchUnavailable(Exception):
    """No web-search backend is configured, or every configured backend failed."""


@dataclass(frozen=True)
class SearchHit:
    title: str = ""
    url: str = ""
    snippet: str = ""


@dataclass(frozen=True)
class WebResult:
    provider: str
    hits: tuple[SearchHit, ...] = ()
    queries: tuple[str, ...] = ()
    # Populated only by a backend that answers directly (e.g. Gemini grounding);
    # generic snippet backends leave these empty for the caller to synthesize.
    text: str = ""
    citations: tuple[Mapping[str, str], ...] = ()
    model: str = ""


@dataclass(frozen=True)
class WebSearchConfig:
    enabled: bool = True
    backend_order: tuple[str, ...] = _DEFAULT_ORDER
    ddg_enabled: bool = True
    searxng_url: str = ""
    tavily_api_key: str = ""
    brave_api_key: str = ""
    google_cse_key: str = ""
    google_cse_cx: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    timeout_seconds: float = _DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "WebSearchConfig":
        source = os.environ if environ is None else environ

        def value(name: str, default: str = "") -> str:
            return str(source.get(name, default) or "").strip()

        raw_order = value("INTELLIGENCE_WEBSEARCH_BACKENDS")
        order = tuple(
            name for name in (item.strip().lower() for item in raw_order.split(","))
            if name in _BACKENDS
        ) or _DEFAULT_ORDER
        return cls(
            enabled=value("INTELLIGENCE_WEBSEARCH_ENABLED", "1") not in ("0", "false", ""),
            backend_order=order,
            ddg_enabled=value("INTELLIGENCE_WEBSEARCH_DDG", "1") not in ("0", "false", ""),
            searxng_url=value("SEARXNG_URL"),
            tavily_api_key=value("TAVILY_API_KEY"),
            brave_api_key=value("BRAVE_SEARCH_API_KEY"),
            google_cse_key=value("GOOGLE_CSE_KEY"),
            google_cse_cx=value("GOOGLE_CSE_CX"),
            gemini_api_key=value("GEMINI_API_KEY") or value("MSB_AI_GEMINI_API_KEY"),
            gemini_model=value("INTELLIGENCE_WEBSEARCH_GEMINI_MODEL", "gemini-3.5-flash"),
        )


class Transport(Protocol):
    """A plain callable, not an object with a `.request` method — `_BaseBackend`
    calls `transport(method, url, headers=..., body=..., timeout_seconds=...)`
    directly, matching `_urllib_transport`'s signature below."""

    def __call__(
        self, method: str, url: str, *, headers: Mapping[str, str],
        body: bytes | None, timeout_seconds: float,
    ) -> tuple[int, bytes]: ...


def _urllib_transport(method, url, *, headers, body, timeout_seconds):
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:  # noqa: BLE001 - any transport failure is "unavailable"
        raise WebSearchUnavailable(f"web backend transport failed: {exc}") from exc


class SearchBackend(Protocol):
    name: str
    grounded: bool

    def available(self) -> bool: ...
    def run(self, query: str, *, timeout_seconds: float) -> WebResult: ...


class _BaseBackend:
    name = ""
    grounded = False

    def __init__(self, config: WebSearchConfig, transport: Transport | None = None) -> None:
        self._config = config
        self._transport = transport or _urllib_transport

    def _send(self, method, url, *, headers=None, body=None, timeout_seconds=_DEFAULT_TIMEOUT):
        return self._transport(method, url, headers=headers or {}, body=body, timeout_seconds=timeout_seconds)


class SearxngBackend(_BaseBackend):
    """A self-hosted SearXNG instance — no API key, no third-party quota."""

    name = "searxng"

    def available(self) -> bool:
        return bool(self._config.searxng_url)

    def run(self, query: str, *, timeout_seconds: float) -> WebResult:
        base = self._config.searxng_url.rstrip("/")
        url = base + "/search?" + urllib.parse.urlencode({
            "q": query, "format": "json", "pageno": 1, "safesearch": 1, "language": "all"})
        status, raw = self._send(
            "GET", url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
            timeout_seconds=timeout_seconds)
        if status >= 400:
            raise WebSearchUnavailable(f"SearXNG HTTP {status}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebSearchUnavailable("SearXNG returned malformed JSON") from exc
        results = sorted(payload.get("results") or [], key=lambda row: row.get("score") or 0, reverse=True)
        hits = tuple(SearchHit(title=row.get("title", ""), url=row.get("url", ""), snippet=row.get("content", ""))
                     for row in results if row.get("url"))
        if not hits:
            raise WebSearchUnavailable("SearXNG: no results")
        return WebResult(provider=self.name, hits=hits, queries=(query,))


class DuckDuckGoBackend(_BaseBackend):
    """Reads DuckDuckGo's public HTML results page — no key, no dependency.

    Less stable than a keyed API (DuckDuckGo can rate-limit a server IP or
    change markup); a parse failure raises so the caller tries the next
    backend rather than returning nothing.
    """

    name = "duckduckgo"
    _ENDPOINT = "https://html.duckduckgo.com/html/"
    _LINK = re.compile(
        r'<a\b[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE)
    _SNIPPET = re.compile(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
    _TAG = re.compile(r"<[^>]+>")

    def available(self) -> bool:
        return self._config.ddg_enabled

    def _clean(self, fragment: str) -> str:
        return html.unescape(self._TAG.sub("", fragment or "")).strip()

    def _unwrap(self, url: str) -> str:
        if url.startswith("//"):
            url = "https:" + url
        parsed = urllib.parse.urlparse(url)
        if parsed.path.startswith("/l/"):
            query = urllib.parse.parse_qs(parsed.query)
            if query.get("uddg"):
                return query["uddg"][0]
        return url

    def run(self, query: str, *, timeout_seconds: float) -> WebResult:
        body = urllib.parse.urlencode({"q": query, "kl": "vn-vi"}).encode("utf-8")
        status, raw = self._send(
            "POST", self._ENDPOINT, body=body,
            headers={"User-Agent": _USER_AGENT,
                     "Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "text/html"},
            timeout_seconds=timeout_seconds)
        if status >= 400:
            raise WebSearchUnavailable(f"DuckDuckGo HTTP {status}")
        text = raw.decode("utf-8", "replace")
        links = self._LINK.findall(text)
        snippets = self._SNIPPET.findall(text)
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for index, (raw_url, raw_title) in enumerate(links):
            resolved = self._unwrap(raw_url or "")
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            snippet = self._clean(snippets[index]) if index < len(snippets) else ""
            hits.append(SearchHit(title=self._clean(raw_title), url=resolved, snippet=snippet))
            if len(hits) >= 8:
                break
        if not hits:
            raise WebSearchUnavailable("DuckDuckGo: could not parse any result")
        return WebResult(provider=self.name, hits=tuple(hits), queries=(query,))


class TavilyBackend(_BaseBackend):
    name = "tavily"

    def available(self) -> bool:
        return bool(self._config.tavily_api_key)

    def run(self, query: str, *, timeout_seconds: float) -> WebResult:
        status, raw = self._send(
            "POST", "https://api.tavily.com/search",
            headers={"Content-Type": "application/json"},
            body=json.dumps({
                "api_key": self._config.tavily_api_key, "query": query,
                "max_results": 6, "search_depth": "basic",
            }).encode("utf-8"),
            timeout_seconds=timeout_seconds)
        if status >= 400:
            raise WebSearchUnavailable(f"Tavily HTTP {status}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebSearchUnavailable("Tavily returned malformed JSON") from exc
        hits = tuple(SearchHit(title=row.get("title", ""), url=row.get("url", ""), snippet=row.get("content", ""))
                     for row in (payload.get("results") or []) if row.get("url"))
        if not hits:
            raise WebSearchUnavailable("Tavily: no results")
        return WebResult(provider=self.name, hits=hits, queries=(query,))


class BraveBackend(_BaseBackend):
    name = "brave"

    def available(self) -> bool:
        return bool(self._config.brave_api_key)

    def run(self, query: str, *, timeout_seconds: float) -> WebResult:
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
            {"q": query, "count": 6})
        status, raw = self._send(
            "GET", url,
            headers={"Accept": "application/json", "X-Subscription-Token": self._config.brave_api_key},
            timeout_seconds=timeout_seconds)
        if status >= 400:
            raise WebSearchUnavailable(f"Brave HTTP {status}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebSearchUnavailable("Brave returned malformed JSON") from exc
        results = ((payload.get("web") or {}).get("results")) or []
        hits = tuple(SearchHit(title=row.get("title", ""), url=row.get("url", ""), snippet=row.get("description", ""))
                     for row in results if row.get("url"))
        if not hits:
            raise WebSearchUnavailable("Brave: no results")
        return WebResult(provider=self.name, hits=hits, queries=(query,))


class GoogleCseBackend(_BaseBackend):
    name = "google_cse"

    def available(self) -> bool:
        return bool(self._config.google_cse_key and self._config.google_cse_cx)

    def run(self, query: str, *, timeout_seconds: float) -> WebResult:
        url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode({
            "key": self._config.google_cse_key, "cx": self._config.google_cse_cx,
            "q": query, "num": 6})
        status, raw = self._send("GET", url, timeout_seconds=timeout_seconds)
        if status >= 400:
            raise WebSearchUnavailable(f"Google CSE HTTP {status}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebSearchUnavailable("Google CSE returned malformed JSON") from exc
        hits = tuple(SearchHit(title=row.get("title", ""), url=row.get("link", ""), snippet=row.get("snippet", ""))
                     for row in (payload.get("items") or []) if row.get("link"))
        if not hits:
            raise WebSearchUnavailable("Google CSE: no results")
        return WebResult(provider=self.name, hits=hits, queries=(query,))


class GeminiGroundingBackend(_BaseBackend):
    """Gemini searches Google and answers directly (grounded); last resort."""

    name = "gemini_grounding"
    grounded = True

    def available(self) -> bool:
        return bool(self._config.gemini_api_key)

    def run(self, query: str, *, timeout_seconds: float, system: str = "") -> WebResult:
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": query[:2000]}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 900},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system[:2000]}]}
        key = self._config.gemini_api_key.split(",")[0].strip()
        url = _GEMINI_REST.format(model=self._config.gemini_model)
        status, raw = self._send(
            "POST", url, headers={"Content-Type": "application/json", "x-goog-api-key": key},
            body=json.dumps(body).encode("utf-8"), timeout_seconds=max(timeout_seconds, 20.0))
        if status in (401, 403):
            raise WebSearchUnavailable("Gemini key lacks Google Search grounding access")
        if status == 429:
            raise WebSearchUnavailable("Gemini grounding is rate-limited")
        if status >= 400:
            raise WebSearchUnavailable(f"Gemini grounding HTTP {status}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebSearchUnavailable("Gemini grounding returned malformed JSON") from exc
        candidates = payload.get("candidates") or []
        if not candidates:
            raise WebSearchUnavailable("Gemini grounding returned no candidates")
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        text = "".join(str(part.get("text", "")) for part in parts).strip()
        if not text:
            raise WebSearchUnavailable("Gemini grounding returned empty text")
        meta = candidates[0].get("groundingMetadata") or {}
        citations: list[dict] = []
        seen: set[str] = set()
        for chunk in meta.get("groundingChunks") or []:
            web = chunk.get("web") or {}
            link = web.get("uri") or ""
            if link and link not in seen:
                seen.add(link)
                citations.append({"title": web.get("title") or link, "url": link})
        queries = tuple(q for q in (meta.get("webSearchQueries") or []) if q) or (query,)
        return WebResult(
            provider=self.name, queries=queries, text=text[:3000],
            citations=tuple(citations), model=self._config.gemini_model)


_BACKENDS: dict[str, type[_BaseBackend]] = {
    "searxng": SearxngBackend,
    "duckduckgo": DuckDuckGoBackend,
    "tavily": TavilyBackend,
    "brave": BraveBackend,
    "google_cse": GoogleCseBackend,
    "gemini_grounding": GeminiGroundingBackend,
}


def pick_backends(config: WebSearchConfig, transport: Transport | None = None) -> tuple[_BaseBackend, ...]:
    """Every configured, available backend, in priority order."""
    out = []
    for name in config.backend_order:
        backend = _BACKENDS[name](config, transport)
        try:
            if backend.available():
                out.append(backend)
        except Exception:  # noqa: BLE001 - a broken availability check just skips the backend
            continue
    return tuple(out)
