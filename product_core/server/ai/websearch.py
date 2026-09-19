# -*- coding: utf-8 -*-
"""Web search — "chân tay" độc lập với "bộ não" (Master Plan §23.1.3).

Nguyên tắc: nhà cung cấp LLM (Gemini / DeepSeek / GreenNode / OpenAI) chỉ là
**bộ não** — thay được. Việc "tra web" là **chân tay + hệ thần kinh** do Radar
sở hữu và phải chạy dù đang cắm bộ não nào.

Kiến trúc: một `SearchBackend` router nhỏ, song song với `ai/router.py`:

* Backend **tự chủ, không khoá**:
  - `searxng` — trỏ tới một instance SearXNG Radar tự dựng (Docker, không SaaS).
  - `duckduckgo` — đọc thẳng endpoint HTML của DuckDuckGo, không cần khoá/gói.
* Backend **generic có khoá** (Tavily / Brave / Google CSE) — chỉ trả kết quả thô.
* Backend **grounded** (Gemini "Google Search grounding") — tự tìm + tự trả lời;
  fallback cuối.

Backend không-grounded chỉ trả kết quả thô (title/url/snippet); Radar tự tổng hợp
bằng **adapter hiện hành** → mọi bộ não đều dùng được. Kết quả web luôn bọc
`prompt_guard` vì nội dung web là dữ liệu đáng ngờ.

Thiết kế adapter tham khảo open-webui (`retrieval/web/*` — cùng shape
`{link,title,snippet}`); code ở đây viết lại, không sao chép.
"""
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .adapter import ModelRequest, get_adapter
from .prompt_guard import GUARD_RULE, wrap_source

_DEFAULT_TIMEOUT = 12
#: Trần CẢ LƯỢT tra web (mọi backend + tổng hợp). Không có nó, lặp qua từng
#: backend (12 s tìm + 20 s tổng hợp mỗi cái) làm một câu "tổng giám đốc
#: Techcombank là ai" mất 103 s trên production 19/09.
WEB_TOTAL_BUDGET = 35.0
_DEFAULT_ORDER = ["searxng", "duckduckgo", "tavily", "brave", "google_cse",
                  "gemini_grounding"]
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36")
_GEMINI_REST = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_DEFAULT_MODEL = "gemini-3.5-flash"


class WebSearchUnavailable(Exception):
    """Web search chưa bật, chưa cấu hình backend nào, hoặc backend lỗi."""


@dataclass
class SearchHit:
    title: str = ""
    url: str = ""
    snippet: str = ""


@dataclass
class WebResult:
    text: str = ""
    citations: list = field(default_factory=list)   # [{"title","url"}]
    queries: list = field(default_factory=list)
    hits: list = field(default_factory=list)        # [SearchHit]
    provider: str = ""            # backend đã tìm: tavily/brave/google_cse/gemini_grounding
    model: str = ""              # bộ não tổng hợp câu trả lời (rỗng nếu grounded)
    synthesized_by: str = ""     # provider của bộ não tổng hợp
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def _env(env):
    return env if env is not None else os.environ


# --------------------------------------------------------------------------- #
# HTTP (urllib, cùng khuôn với ai/providers.py — không kéo SDK)
# --------------------------------------------------------------------------- #
def _http(url, *, method="GET", headers=None, body=None, timeout=_DEFAULT_TIMEOUT):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:                          # noqa: BLE001
            return exc.code, {}
    except Exception as exc:                       # noqa: BLE001
        raise WebSearchUnavailable(f"không gọi được backend web: {exc}") from exc


def _http_text(url, *, method="GET", headers=None, data=None, timeout=_DEFAULT_TIMEOUT):
    """Trả (status, text). `data` là bytes form-encoded (POST) hoặc None."""
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, response.read().decode(charset, "replace")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read().decode("utf-8", "replace")
        except Exception:                          # noqa: BLE001
            return exc.code, ""
    except Exception as exc:                       # noqa: BLE001
        raise WebSearchUnavailable(f"không gọi được backend web: {exc}") from exc


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class SearchBackend:
    name = ""
    grounded = False

    def __init__(self, env=None, transport=None):
        self.env = _env(env)
        self._transport = transport      # test tiêm; (url, method, headers, body, timeout)->(status, payload)

    def available(self):
        raise NotImplementedError

    def run(self, query, *, timeout=_DEFAULT_TIMEOUT):
        raise NotImplementedError

    def _send(self, url, *, method="GET", headers=None, body=None, timeout=_DEFAULT_TIMEOUT):
        if self._transport is not None:
            return self._transport(url, method, headers or {}, body, timeout)
        return _http(url, method=method, headers=headers, body=body, timeout=timeout)

    def _send_text(self, url, *, method="GET", headers=None, data=None,
                   timeout=_DEFAULT_TIMEOUT):
        if self._transport is not None:
            return self._transport(url, method, headers or {}, data, timeout)
        return _http_text(url, method=method, headers=headers, data=data, timeout=timeout)


class SearxngBackend(SearchBackend):
    """Instance SearXNG do Radar tự dựng (Docker) — không SaaS, không khoá."""

    name = "searxng"

    def _base(self):
        return (self.env.get("SEARXNG_URL") or self.env.get("SEARXNG_BASE_URL")
                or "").strip().rstrip("/")

    def available(self):
        return bool(self._base())

    def run(self, query, *, timeout=_DEFAULT_TIMEOUT):
        url = (self._base() + "/search?"
               + urllib.parse.urlencode({
                   "q": query, "format": "json", "pageno": 1,
                   "safesearch": 1, "language": "all"}))
        status, payload = self._send(
            url, headers={"Accept": "application/json", "User-Agent": _UA},
            timeout=timeout)
        if status >= 400 or not isinstance(payload, dict):
            raise WebSearchUnavailable(f"SearXNG HTTP {status}.")
        results = sorted(payload.get("results") or [],
                         key=lambda r: r.get("score") or 0, reverse=True)
        hits = [SearchHit(title=r.get("title", ""), url=r.get("url", ""),
                          snippet=r.get("content", ""))
                for r in results if r.get("url")]
        return WebResult(hits=hits, provider=self.name, queries=[query])


class DuckDuckGoBackend(SearchBackend):
    """Đọc thẳng endpoint HTML của DuckDuckGo — không khoá, không gói phụ thuộc.

    Kém ổn định hơn SearXNG (DDG có thể giới hạn IP máy chủ / đổi markup); dùng
    làm phương án không cần hạ tầng. Không parse được → raise để router lùi tiếp.
    """

    name = "duckduckgo"
    _ENDPOINT = "https://html.duckduckgo.com/html/"
    _LINK = re.compile(
        r'<a\b[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE)
    _SNIP = re.compile(
        r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE)
    _TAG = re.compile(r"<[^>]+>")

    def available(self):
        # Luôn "có" (không cần cấu hình); chỉ bật khi được đưa vào thứ tự backend.
        return self.env.get("ASSISTANT_WEBSEARCH_DDG", "1").strip() not in ("0", "false", "")

    def _clean(self, fragment):
        return html.unescape(self._TAG.sub("", fragment or "")).strip()

    def _unwrap(self, url):
        # DDG bọc link: /l/?uddg=<encoded>&...
        if url.startswith("//"):
            url = "https:" + url
        parsed = urllib.parse.urlparse(url)
        if parsed.path.startswith("/l/"):
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("uddg"):
                return qs["uddg"][0]
        return url

    def run(self, query, *, timeout=_DEFAULT_TIMEOUT):
        data = urllib.parse.urlencode({"q": query, "kl": "vn-vi"}).encode("utf-8")
        status, text = self._send_text(
            self._ENDPOINT, method="POST", data=data,
            headers={"User-Agent": _UA,
                     "Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "text/html"},
            timeout=timeout)
        if status >= 400 or not isinstance(text, str) or not text:
            raise WebSearchUnavailable(f"DuckDuckGo HTTP {status}.")
        links = self._LINK.findall(text)
        snips = self._SNIP.findall(text)
        hits, seen = [], set()
        for i, (raw_url, raw_title) in enumerate(links):
            u = self._unwrap(raw_url or "")
            if not u or u in seen:
                continue
            seen.add(u)
            snippet = self._clean(snips[i]) if i < len(snips) else ""
            hits.append(SearchHit(title=self._clean(raw_title), url=u, snippet=snippet))
            if len(hits) >= 8:
                break
        if not hits:
            raise WebSearchUnavailable("DuckDuckGo: không tách được kết quả.")
        return WebResult(hits=hits, provider=self.name, queries=[query])


class TavilyBackend(SearchBackend):
    name = "tavily"

    def available(self):
        return bool(self.env.get("TAVILY_API_KEY", "").strip())

    def run(self, query, *, timeout=_DEFAULT_TIMEOUT):
        key = self.env.get("TAVILY_API_KEY", "").strip()
        status, payload = self._send(
            "https://api.tavily.com/search", method="POST",
            headers={"Content-Type": "application/json"},
            body={"api_key": key, "query": query, "max_results": 6,
                  "search_depth": "basic"},
            timeout=timeout)
        if status >= 400:
            raise WebSearchUnavailable(f"Tavily HTTP {status}.")
        hits = [SearchHit(title=r.get("title", ""), url=r.get("url", ""),
                          snippet=r.get("content", ""))
                for r in (payload.get("results") or []) if r.get("url")]
        return WebResult(hits=hits, provider=self.name, queries=[query],
                         raw={"answer": payload.get("answer", "")})


class BraveBackend(SearchBackend):
    name = "brave"

    def available(self):
        return bool(self.env.get("BRAVE_SEARCH_API_KEY", "").strip())

    def run(self, query, *, timeout=_DEFAULT_TIMEOUT):
        key = self.env.get("BRAVE_SEARCH_API_KEY", "").strip()
        url = ("https://api.search.brave.com/res/v1/web/search?"
               + urllib.parse.urlencode({"q": query, "count": 6}))
        status, payload = self._send(
            url, headers={"Accept": "application/json", "X-Subscription-Token": key},
            timeout=timeout)
        if status >= 400:
            raise WebSearchUnavailable(f"Brave HTTP {status}.")
        results = ((payload.get("web") or {}).get("results")) or []
        hits = [SearchHit(title=r.get("title", ""), url=r.get("url", ""),
                          snippet=r.get("description", ""))
                for r in results if r.get("url")]
        return WebResult(hits=hits, provider=self.name, queries=[query])


class GoogleCseBackend(SearchBackend):
    name = "google_cse"

    def available(self):
        return bool(self.env.get("GOOGLE_CSE_KEY", "").strip()
                    and self.env.get("GOOGLE_CSE_CX", "").strip())

    def run(self, query, *, timeout=_DEFAULT_TIMEOUT):
        url = ("https://www.googleapis.com/customsearch/v1?"
               + urllib.parse.urlencode({
                   "key": self.env.get("GOOGLE_CSE_KEY", "").strip(),
                   "cx": self.env.get("GOOGLE_CSE_CX", "").strip(),
                   "q": query, "num": 6}))
        status, payload = self._send(url, timeout=timeout)
        if status >= 400:
            raise WebSearchUnavailable(f"Google CSE HTTP {status}.")
        hits = [SearchHit(title=r.get("title", ""), url=r.get("link", ""),
                          snippet=r.get("snippet", ""))
                for r in (payload.get("items") or []) if r.get("link")]
        return WebResult(hits=hits, provider=self.name, queries=[query])


class GeminiGroundingBackend(SearchBackend):
    """Gemini tự tìm Google + tự trả lời (grounded). Fallback cuối."""

    name = "gemini_grounding"
    grounded = True

    def available(self):
        return bool(self.env.get("MSB_AI_GEMINI_API_KEY", "").strip())

    def _model(self):
        return (self.env.get("MSB_AI_WEBSEARCH_MODEL")
                or self.env.get("MSB_AI_GEMINI_MODEL")
                or _GEMINI_DEFAULT_MODEL)

    def run(self, query, *, timeout=_DEFAULT_TIMEOUT, system=""):
        model = self._model()
        body = {
            "contents": [{"role": "user", "parts": [{"text": query[:2000]}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 900},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system[:2000]}]}
        # MSB_AI_GEMINI_API_KEY có thể là nhiều khoá phân tách bằng dấu phẩy
        # (provider OpenAI-compat xoay vòng) — REST grounding chỉ nhận một khoá.
        key = self.env.get("MSB_AI_GEMINI_API_KEY", "").split(",")[0].strip()
        status, payload = self._send(
            _GEMINI_REST.format(model=model), method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            body=body, timeout=max(timeout, 20))
        if status in (401, 403):
            raise WebSearchUnavailable("Khoá Gemini không có quyền Google Search.")
        if status == 429:
            raise WebSearchUnavailable("Google đang giới hạn tốc độ.")
        if status >= 400:
            detail = (payload.get("error") or {}).get("message", "")
            raise WebSearchUnavailable(f"Gemini grounding HTTP {status}. {detail}".strip())

        candidates = payload.get("candidates") or []
        if not candidates:
            block = (payload.get("promptFeedback") or {}).get("blockReason")
            raise WebSearchUnavailable(f"Google không trả kết quả ({block or 'không rõ'}).")
        cand = candidates[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        meta = cand.get("groundingMetadata") or {}
        citations, seen = [], set()
        for chunk in meta.get("groundingChunks") or []:
            web = chunk.get("web") or {}
            u = web.get("uri") or ""
            if u and u not in seen:
                seen.add(u)
                citations.append({"title": web.get("title") or u, "url": u})
        return WebResult(
            text=text, citations=citations, provider=self.name, model=model,
            queries=[q for q in (meta.get("webSearchQueries") or []) if q] or [query],
            usage=payload.get("usageMetadata") or {})


_BACKENDS = {
    "searxng": SearxngBackend,
    "duckduckgo": DuckDuckGoBackend,
    "tavily": TavilyBackend,
    "brave": BraveBackend,
    "google_cse": GoogleCseBackend,
    "gemini_grounding": GeminiGroundingBackend,
}


def _order(env):
    from django.conf import settings
    raw = (env.get("ASSISTANT_WEBSEARCH_BACKENDS")
           or getattr(settings, "ASSISTANT_WEBSEARCH_BACKENDS", "") or "")
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    names = [n for n in names if n in _BACKENDS]
    return names or _DEFAULT_ORDER


def pick_backends(env=None, transport=None):
    """Mọi backend khả dụng, theo thứ tự ưu tiên."""
    env = _env(env)
    out = []
    for name in _order(env):
        backend = _BACKENDS[name](env=env, transport=transport)
        try:
            if backend.available():
                out.append(backend)
        except Exception:                          # noqa: BLE001
            continue
    return out


def pick_backend(env=None, transport=None):
    """Backend khả dụng đầu tiên. None nếu chưa cấu hình gì."""
    picks = pick_backends(env, transport=transport)
    return picks[0] if picks else None


def enabled(env=None):
    """Web search chạy khi được bật tường minh VÀ có ít nhất một backend."""
    from django.conf import settings
    if not getattr(settings, "ASSISTANT_WEB_SEARCH", False):
        return False
    return pick_backend(env) is not None


def _format_hits(hits, limit=6):
    lines = []
    for i, h in enumerate(hits[:limit], 1):
        lines.append(f"[{i}] {h.title}\n{h.url}\n{h.snippet}".strip())
    return "\n\n".join(lines)


def _synthesize(question, hits, *, system, adapter, budget=20):
    """Cho bộ não hiện hành viết câu trả lời từ kết quả web (đã bọc guard)."""
    model = adapter or get_adapter()
    sources_block = wrap_source(_format_hits(hits), "KẾT QUẢ TÌM KIẾM WEB")
    messages = [
        {"role": "system", "content": f"{system}\n\n{GUARD_RULE}"},
        {"role": "user", "content": f"{question}\n\n{sources_block}\n\n"
                                    "Trả lời câu hỏi dựa trên các kết quả trên, "
                                    "bằng tiếng Việt, ngắn gọn, nêu mốc thời gian "
                                    "nếu có. Không bịa thông tin ngoài kết quả."},
    ]
    # Leash ngắn: nếu bộ não chậm/treo khi tổng hợp, bỏ nhanh để web_answer lùi
    # sang backend kế (vd gemini_grounding tự trả lời) thay vì bắt người dùng đợi.
    # reasoning_effort="none": model có bước "suy nghĩ" (Gemini 3.5 Flash, GLM)
    # ăn hết max_tokens rồi cắt cụt câu trả lời — tổng hợp web không cần suy nghĩ dài.
    request = ModelRequest(messages=messages, task="assistant_web",
                           temperature=0.2, max_tokens=1200,
                           extra={"budget_seconds": budget, "reasoning_effort": "none"},
                           meta={"router": "websearch_synthesis"})
    return model.complete(request)


def web_answer(question, *, system="", adapter=None, timeout=None, env=None,
               transport=None):
    """Trả `WebResult` với `.text` đã điền. Raise `WebSearchUnavailable` khi hỏng.

    `question` là văn bản người dùng gõ; lớp gọi phải đã loại PII (`ai.pii`).
    `system` là chỉ dẫn hệ thống (persona + yêu cầu trích nguồn).
    `adapter` là bộ não dùng để tổng hợp khi backend là loại generic.
    """
    q = str(question or "").strip()
    if not q:
        raise WebSearchUnavailable("Câu hỏi rỗng.")

    backends = pick_backends(env, transport=transport)
    if not backends:
        raise WebSearchUnavailable(
            "Chưa cấu hình backend web nào (mặc định dùng duckduckgo — kiểm tra "
            "ASSISTANT_WEBSEARCH_DDG / SEARXNG_URL / *_API_KEY).")

    wait = timeout or _DEFAULT_TIMEOUT
    deadline = time.monotonic() + WEB_TOTAL_BUDGET
    last = None
    for backend in backends:
        remaining = deadline - time.monotonic()
        if remaining < 5:
            last = WebSearchUnavailable(f"hết ngân sách tra web ({WEB_TOTAL_BUDGET:.0f}s)")
            break
        wait = min(wait, remaining)
        try:
            if backend.grounded:
                result = backend.run(q, timeout=wait, system=system)
                if not result.text:
                    raise WebSearchUnavailable("backend grounded không trả nội dung")
                return result
            result = backend.run(q, timeout=wait)
            if not result.hits:
                raise WebSearchUnavailable(f"{backend.name}: không có kết quả")
        except WebSearchUnavailable as exc:
            last = exc
            continue

        try:
            response = _synthesize(q, result.hits, system=system, adapter=adapter,
                                   budget=max(5, min(20, deadline - time.monotonic())))
        except Exception as exc:                       # noqa: BLE001
            # Bộ não lỗi/timeout khi tổng hợp → thử backend kế (vd gemini_grounding
            # tự trả lời), rồi mới bỏ cuộc. KHÔNG để ModelError lọt ra ngoài.
            last = WebSearchUnavailable(f"tổng hợp lỗi: {exc}")
            continue
        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            last = WebSearchUnavailable("bộ não không tổng hợp được câu trả lời")
            continue
        result.text = text[:3000]
        result.model = getattr(response, "model", "") or ""
        result.synthesized_by = getattr(response, "provider", "") or ""
        result.citations = [{"title": h.title or h.url, "url": h.url}
                            for h in result.hits[:6] if h.url]
        usage = getattr(response, "usage", None)
        if hasattr(usage, "as_dict"):
            result.usage = usage.as_dict()
        return result

    raise WebSearchUnavailable(f"mọi backend web đều lỗi. Lỗi cuối: {last}")
