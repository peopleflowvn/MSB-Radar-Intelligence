from __future__ import annotations

from pathlib import Path
import json
import logging
import threading
import time

from radar_intelligence.api.codec import encode_answer_response, encode_search_hit
from radar_intelligence.agent import GroundedAnswerGraph
from radar_intelligence.auth import RadarScopeConfig, RadarScopeValidator
from radar_intelligence.config import RuntimeSettings
from radar_intelligence.contracts import AnswerResponse, ModelTrace, SearchRequest
from radar_intelligence.evidence import (
    RadarHttpSourceResolver, RadarResolverConfig, resolve_citations,
)
from radar_intelligence.indexing import SqliteDocumentIndex
from radar_intelligence.observability import safe_span
from radar_intelligence.providers import (
    Capability, GatewayRequest, GreenNodeConfig, GreenNodeEmbedder,
    GreenNodeTransport, ModelGateway, ProviderError, UrllibHttpClient,
)
from radar_intelligence.retrieval import (
    CosineSemanticRanker, HaystackBM25Ranker, HybridRetriever, RetrievalScope,
    project_search_documents,
)
from radar_intelligence.websearch import (
    WebSearchConfig, WebSearchUnavailable, contains_pii, scan_injection, web_answer,
)

_WEB_ANSWER_SYSTEM = (
    "Ban la tro ly Radar. Khong tim thay bang chung ung vien phu hop trong pham vi "
    "duoc phep cho cau hoi nay, nhung day co the la mot cau hoi kien thuc chung. "
    "Tra loi ngan gon bang tieng Viet, CHI dua tren ket qua tim duoc tren web, neu "
    "moc thoi gian cua so lieu neu co, khong suy doan ngoai nguon."
)


# Grounded generation is prompted for JSON but models commonly wrap it in a
# markdown code fence, or add a stray leading/trailing word, despite the
# instruction. Try the strict parse first, then two tolerant fallbacks, before
# treating the response as genuinely malformed.
def _parse_grounded_json(text: str) -> dict:
    candidates = [text]
    stripped = text.strip()
    if stripped.startswith("```"):
        fenced = stripped.strip("`").strip()
        if fenced[:4].lower() == "json":
            fenced = fenced[4:].strip()
        candidates.append(fenced)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("model returned malformed grounded answer")


# Caps the evidence text handed to the model per answer. Evidence chunks are
# already bounded to ~1200 chars each by DocumentConverter, but the hit count
# (up to 10 people x 3 evidence each) is not otherwise bounded end to end;
# this keeps prompt size/cost predictable without truncating the common case.
_MAX_CONTEXT_CHARS = 24_000


def _scope_records(records, person_ids, knowledge_ids, knowledge_only=False):
    """Apply a request's explicit narrowing/opt-in before retrieval sees records.

    `person_ids` (if non-empty) narrows the candidate corpus to exactly those
    ids, as today. Independently, any record whose person_id marks it as a
    non-candidate entity (e.g. an internal-knowledge document indexed as its
    own negative-id "person") is dropped unless it is explicitly named in
    `knowledge_ids` — that set's default is "none", the opposite of
    `person_ids`' "no restriction", since a knowledge document must never
    become visible merely because a caller did not restrict candidate scope.

    `knowledge_only` drops every candidate record, leaving just the allowed
    knowledge documents.
    """
    allowed_person_ids = set(person_ids)
    allowed_knowledge_ids = set(knowledge_ids)
    result = []
    for row in records:
        identity = row.chunk.person.person_id
        if identity.startswith("-"):
            if identity in allowed_knowledge_ids:
                result.append(row)
        elif knowledge_only:
            continue
        elif not allowed_person_ids or identity in allowed_person_ids:
            result.append(row)
    return tuple(result)


def _bounded_context(evidence) -> list[dict]:
    items: list[dict] = []
    total = 0
    for row in evidence:
        items.append({"evidence_id": row.evidence_id, "person_id": row.person_id, "text": row.text})
        total += len(row.text)
        if total >= _MAX_CONTEXT_CHARS:
            break
    return items


class _ProviderResilientSemanticRanker:
    """Use lexical RAG when only the remote embedding provider is unavailable."""

    def __init__(self, delegate: CosineSemanticRanker) -> None:
        self._delegate = delegate
        self._logger = logging.getLogger(__name__)

    def rank(self, query, records):
        try:
            return self._delegate.rank(query, records)
        except ProviderError as exc:
            # Query text and candidate records can contain PII, so neither is logged.
            self._logger.warning("semantic retrieval temporarily unavailable: %s", exc)
            return ()

    def prepare(self, records):
        self._delegate.prepare(records)


class SearchService:
    def __init__(
        self,
        settings: RuntimeSettings,
        database: str | Path,
        *,
        refresh_interval_seconds: float = 5.0,
        websearch_transport=None,
    ) -> None:
        if not settings.ready:
            raise ValueError("runtime settings are incomplete")
        values = settings.values
        self._scope = RadarScopeValidator(RadarScopeConfig(
            values["RADAR_BASE_URL"], values["RADAR_SERVICE_TOKEN"]))
        provider_config = GreenNodeConfig(
            values["GREENNODE_BASE_URL"], values["GREENNODE_API_KEY"])
        embedder = GreenNodeEmbedder(
            provider_config,
            values["GREENNODE_MODEL_EMBEDDING"],
            http_client=UrllibHttpClient(retry_attempts=1),
            timeout_seconds=3.0,
        )
        self._gateway = ModelGateway({
            Capability.FAST: values["GREENNODE_MODEL_FAST"],
            Capability.DEEP: values["GREENNODE_MODEL_DEEP"],
            Capability.VISION: values["GREENNODE_MODEL_VISION"],
            Capability.EMBEDDING: values["GREENNODE_MODEL_EMBEDDING"],
        }, GreenNodeTransport(provider_config))
        self._resolver = RadarHttpSourceResolver(RadarResolverConfig(
            values["RADAR_BASE_URL"], values["RADAR_SERVICE_TOKEN"]))
        self._websearch_config = WebSearchConfig.from_env()
        self._websearch_transport = websearch_transport
        # Haystack BM25 is deliberately request-local: authorization and structured
        # filters are applied by HybridRetriever before any candidate is handed to it.
        self._semantic_ranker = _ProviderResilientSemanticRanker(CosineSemanticRanker(embedder))
        self._lexical_ranker = HaystackBM25Ranker()
        self._retriever = HybridRetriever(
            self._semantic_ranker,
            lexical_ranker=self._lexical_ranker)
        self._database = Path(database)
        self._index = SqliteDocumentIndex(self._database)
        self._logger = logging.getLogger(__name__)
        self._records_lock = threading.Lock()
        self._records_mtime_ns = -1
        self._records = ()
        self._reload_records(force=True)
        self._answer_graph = GroundedAnswerGraph(
            self._agent_prepare, self._agent_retrieve,
            self._agent_no_evidence, self._agent_generate)
        # Rebuilding the in-memory index (numpy matrix, BM25 store) can take
        # long enough on tens of thousands of chunks to be visible as request
        # latency. A background thread absorbs that cost off the request path;
        # requests always read the last fully-built snapshot instead of racing
        # each other to rebuild it inline.
        self._refresh_interval = refresh_interval_seconds
        self._stop_refresh = threading.Event()
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop, name="intelligence-index-refresh", daemon=True)
        self._refresh_thread.start()

    def close(self) -> None:
        self._stop_refresh.set()
        self._refresh_thread.join(timeout=self._refresh_interval + 5.0)

    def _refresh_loop(self) -> None:
        while not self._stop_refresh.wait(self._refresh_interval):
            try:
                self._reload_records()
            except Exception:
                # A refresh failure must not take the service down; keep
                # serving the last good snapshot and retry on the next tick.
                self._logger.exception("background index refresh failed")

    def _reload_records(self, *, force: bool = False) -> bool:
        try:
            modified = self._database.stat().st_mtime_ns
        except FileNotFoundError:
            modified = -1
        if not force and modified == self._records_mtime_ns:
            return False
        records = project_search_documents(self._index.documents())
        self._semantic_ranker.prepare(records)
        self._lexical_ranker.prepare(records)
        with self._records_lock:
            self._records = records
            self._records_mtime_ns = modified
        return True

    def _current_records(self):
        with self._records_lock:
            return self._records

    def search(self, request):
        if not self._scope.validate(request.scope_token):
            return None
        records = _scope_records(
            self._current_records(), request.person_ids, request.knowledge_ids,
            getattr(request, "knowledge_only", False))
        person_ids = frozenset(record.chunk.person.person_id for record in records)
        if not person_ids:
            return []
        hits = self._retriever.search(request, records, RetrievalScope(person_ids))
        return [encode_search_hit(hit) for hit in hits]

    def index_status(self):
        return self._index.statistics()

    def answer(self, request):
        with safe_span("grounded-answer", {
                "execution_class": "grounded_answer",
                "has_thread": bool(request.thread_id),
                "person_scope_count": len(request.person_ids)}):
            return self._answer_graph.invoke(request)

    def _agent_prepare(self, state):
        request = state["request"]
        with safe_span("authorize-and-scope"):
            if not self._scope.validate(request.scope_token):
                return {"authorized": False, "result": None}
            records = self._current_records()
        records = _scope_records(records, request.person_ids, request.knowledge_ids)
        person_ids = frozenset(row.chunk.person.person_id for row in records)
        return {"authorized": True, "records": records, "person_ids": person_ids}

    def _agent_retrieve(self, state):
        request = state["request"]
        with safe_span("retrieve-evidence", {
                "authorized_person_count": len(state["person_ids"])}):
            hits = tuple(self._retriever.search(
                SearchRequest(request.question, request.scope_token,
                              request.principal_id, limit=10),
                state["records"], RetrievalScope(state["person_ids"])))
        evidence = tuple(item for hit in hits for item in hit.evidence)
        return {"hits": hits, "evidence": evidence}

    def _agent_no_evidence(self, state):
        """No CV evidence matched. Fall back to a best-effort web answer instead
        of a bare refusal — but never for a question that itself carries PII or
        looks like an injection attempt (that text must not reach a public
        search backend), and never in a way that can fail the request: any
        web-search problem here silently falls through to the refusal.
        """
        request = state["request"]
        question = request.question
        if not contains_pii(question) and not scan_injection(question):
            started = time.perf_counter()
            try:
                with safe_span("web-search-fallback"):
                    answer = web_answer(
                        question, system=_WEB_ANSWER_SYSTEM, config=self._websearch_config,
                        gateway=self._gateway, transport=self._websearch_transport,
                        timeout_seconds=12.0)
            except WebSearchUnavailable:
                answer = None
            except Exception:  # noqa: BLE001 - web fallback must never fail the request
                self._logger.exception("web-search fallback failed unexpectedly")
                answer = None
            if answer is not None:
                latency = round((time.perf_counter() - started) * 1000)
                trace = (ModelTrace("web_search", answer.provider, answer.model, latency),)
                return {"result": encode_answer_response(AnswerResponse(
                    answer.text, (), (), (),
                    {"query": question, "grounded": False, "source": "web",
                     "provider": answer.provider, "web_queries": list(answer.queries),
                     "web_citations": [dict(item) for item in answer.citations],
                     "orchestrator": "langgraph"},
                    trace))}
        return {"result": encode_answer_response(AnswerResponse(
            "Không tìm thấy bằng chứng phù hợp trong phạm vi được phép.",
            (), (), (), {"query": question, "grounded": True,
                         "orchestrator": "langgraph"}, ()))}

    def _agent_generate(self, state):
        request = state["request"]
        evidence = state["evidence"]
        context = _bounded_context(evidence)
        prompt = (
            "Trả lời bằng tiếng Việt chỉ từ bằng chứng JSON sau. "
            "Không suy diễn ngoài bằng chứng. Trả về JSON duy nhất có dạng "
            '{"answer":"...","cited_evidence_ids":["..."]}.\n'
            f"Câu hỏi: {request.question}\nBằng chứng: "
            + json.dumps(context, ensure_ascii=False)
        )
        started = time.perf_counter()
        with safe_span("generate-grounded-answer", {
                "candidate_count": len(state["hits"]),
                "evidence_count": len(evidence)}):
            completion = self._gateway.complete(GatewayRequest(Capability.DEEP, prompt, 60))
        latency = round((time.perf_counter() - started) * 1000)
        try:
            generated = _parse_grounded_json(completion.output_text)
            answer = generated["answer"]
            cited_ids = tuple(generated["cited_evidence_ids"])
            if not isinstance(answer, str) or not answer.strip() or any(
                    not isinstance(value, str) for value in cited_ids):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("model returned malformed grounded answer") from exc
        validated = resolve_citations(
            evidence, cited_ids, allowed_person_ids=set(state["person_ids"]),
            scope_token=request.scope_token, resolver=self._resolver)
        cited_people = {row.person_id for row in validated}
        people = tuple(hit.person for hit in state["hits"] if hit.person.person_id in cited_people)
        trace = (ModelTrace(
            Capability.DEEP.value, completion.provider, completion.model_alias, latency,
            completion.input_tokens, completion.output_tokens, completion.request_id),)
        return {"result": encode_answer_response(AnswerResponse(
            answer.strip(), people, validated, cited_ids,
            {"query": request.question, "grounded": True,
             "orchestrator": "langgraph"}, trace))}
