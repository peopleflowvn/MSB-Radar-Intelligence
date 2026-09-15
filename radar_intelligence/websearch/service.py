from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from radar_intelligence.providers import Capability, GatewayRequest, ModelGateway, ProviderError

from .backends import Transport, WebSearchConfig, WebSearchUnavailable, pick_backends
from .guard import GUARD_RULE, wrap_source


@dataclass(frozen=True)
class WebAnswer:
    text: str
    citations: tuple[Mapping[str, str], ...]
    queries: tuple[str, ...]
    provider: str
    model: str


def _format_hits(hits: Sequence, limit: int = 6) -> str:
    lines = []
    for index, hit in enumerate(hits[:limit], start=1):
        lines.append(f"[{index}] {hit.title}\n{hit.url}\n{hit.snippet}".strip())
    return "\n\n".join(lines)


def _synthesize(question: str, hits: Sequence, *, system: str, gateway: ModelGateway, timeout_seconds: float):
    sources_block = wrap_source(_format_hits(hits), "KET QUA TIM KIEM WEB")
    prompt = (
        f"{system}\n\n{GUARD_RULE}\n\n"
        f"Cau hoi: {question}\n\n{sources_block}\n\n"
        "Tra loi bang tieng Viet, ngan gon, dua tren cac ket qua tren. "
        "Neu ket qua co moc thoi gian thi neu ro. Khong bia thong tin ngoai nguon."
    )
    return gateway.complete(GatewayRequest(Capability.FAST, prompt, timeout_seconds))


def web_answer(
    question: str,
    *,
    system: str,
    config: WebSearchConfig,
    gateway: ModelGateway,
    transport: Transport | None = None,
    timeout_seconds: float | None = None,
) -> WebAnswer:
    """Try each configured web-search backend in priority order.

    Raises WebSearchUnavailable when no backend is configured or every one
    failed. Callers must treat that as "fall back to the existing behavior",
    never as a request-ending error — web search is a best-effort widening of
    what the service can answer, not a dependency the answer path requires.
    """
    question = str(question or "").strip()
    if not question:
        raise WebSearchUnavailable("question must not be empty")
    if not config.enabled:
        raise WebSearchUnavailable("web search is disabled")

    backends = pick_backends(config, transport)
    if not backends:
        raise WebSearchUnavailable("no web-search backend is configured")

    wait = timeout_seconds or config.timeout_seconds
    last: Exception | None = None
    for backend in backends:
        try:
            if backend.grounded:
                result = backend.run(question, timeout_seconds=wait, system=system)
                return WebAnswer(result.text, result.citations, result.queries, result.provider, result.model)
            result = backend.run(question, timeout_seconds=wait)
        except WebSearchUnavailable as exc:
            last = exc
            continue

        try:
            completion = _synthesize(
                question, result.hits, system=system, gateway=gateway, timeout_seconds=wait)
        except ProviderError as exc:
            last = WebSearchUnavailable(f"synthesis failed: {exc}")
            continue
        text = str(completion.output_text or "").strip()
        if not text:
            last = WebSearchUnavailable(f"{backend.name}: empty synthesis")
            continue
        citations = tuple(
            {"title": hit.title or hit.url, "url": hit.url} for hit in result.hits[:6] if hit.url)
        return WebAnswer(text[:3000], citations, result.queries, result.provider, completion.model_alias)

    raise WebSearchUnavailable(f"every web-search backend failed: {last}")
