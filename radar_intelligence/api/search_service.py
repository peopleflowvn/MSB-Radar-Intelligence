from __future__ import annotations

from pathlib import Path
import json
import logging
import time

from radar_intelligence.api.codec import encode_answer_response, encode_search_hit
from radar_intelligence.auth import RadarScopeConfig, RadarScopeValidator
from radar_intelligence.config import RuntimeSettings
from radar_intelligence.contracts import AnswerResponse, ModelTrace, SearchRequest
from radar_intelligence.evidence import (
    RadarHttpSourceResolver, RadarResolverConfig, resolve_citations,
)
from radar_intelligence.indexing import SqliteDocumentIndex
from radar_intelligence.providers import (
    Capability, GatewayRequest, GreenNodeConfig, GreenNodeEmbedder,
    GreenNodeTransport, ModelGateway, ProviderError,
)
from radar_intelligence.retrieval import (
    CosineSemanticRanker, HaystackBM25Ranker, HybridRetriever, RetrievalScope,
    project_search_documents,
)


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


class SearchService:
    def __init__(self, settings: RuntimeSettings, database: str | Path) -> None:
        if not settings.ready:
            raise ValueError("runtime settings are incomplete")
        values = settings.values
        self._scope = RadarScopeValidator(RadarScopeConfig(
            values["RADAR_BASE_URL"], values["RADAR_SERVICE_TOKEN"]))
        provider_config = GreenNodeConfig(
            values["GREENNODE_BASE_URL"], values["GREENNODE_API_KEY"])
        embedder = GreenNodeEmbedder(
            provider_config, values["GREENNODE_MODEL_EMBEDDING"], timeout_seconds=5.0,
        )
        self._gateway = ModelGateway({
            Capability.FAST: values["GREENNODE_MODEL_FAST"],
            Capability.DEEP: values["GREENNODE_MODEL_DEEP"],
            Capability.VISION: values["GREENNODE_MODEL_VISION"],
            Capability.EMBEDDING: values["GREENNODE_MODEL_EMBEDDING"],
        }, GreenNodeTransport(provider_config))
        self._resolver = RadarHttpSourceResolver(RadarResolverConfig(
            values["RADAR_BASE_URL"], values["RADAR_SERVICE_TOKEN"]))
        # Haystack BM25 is deliberately request-local: authorization and structured
        # filters are applied by HybridRetriever before any candidate is handed to it.
        self._retriever = HybridRetriever(
            _ProviderResilientSemanticRanker(CosineSemanticRanker(embedder)),
            lexical_ranker=HaystackBM25Ranker())
        self._index = SqliteDocumentIndex(database)

    def search(self, request):
        if not self._scope.validate(request.scope_token):
            return None
        records = project_search_documents(self._index.documents())
        person_ids = frozenset(record.chunk.person.person_id for record in records)
        if not person_ids:
            return []
        hits = self._retriever.search(request, records, RetrievalScope(person_ids))
        return [encode_search_hit(hit) for hit in hits]

    def index_status(self):
        return self._index.statistics()

    def answer(self, request):
        if not self._scope.validate(request.scope_token):
            return None
        records = project_search_documents(self._index.documents())
        if request.person_ids:
            requested = set(request.person_ids)
            records = tuple(row for row in records if row.chunk.person.person_id in requested)
        person_ids = frozenset(row.chunk.person.person_id for row in records)
        if not person_ids:
            return encode_answer_response(AnswerResponse(
                "Không tìm thấy bằng chứng phù hợp trong phạm vi được phép.",
                (), (), (), {"query": request.question}, ()))
        hits = self._retriever.search(
            SearchRequest(request.question, request.scope_token, request.principal_id, limit=10),
            records, RetrievalScope(person_ids))
        evidence = tuple(item for hit in hits for item in hit.evidence)
        if not evidence:
            return encode_answer_response(AnswerResponse(
                "Không tìm thấy bằng chứng phù hợp trong phạm vi được phép.",
                (), (), (), {"query": request.question}, ()))
        context = [{"evidence_id": row.evidence_id, "person_id": row.person_id,
                    "text": row.text} for row in evidence]
        prompt = (
            "Trả lời bằng tiếng Việt chỉ từ bằng chứng JSON sau. "
            "Không suy diễn ngoài bằng chứng. Trả về JSON duy nhất có dạng "
            '{"answer":"...","cited_evidence_ids":["..."]}.\n'
            f"Câu hỏi: {request.question}\nBằng chứng: "
            + json.dumps(context, ensure_ascii=False)
        )
        started = time.perf_counter()
        completion = self._gateway.complete(GatewayRequest(Capability.DEEP, prompt, 60))
        latency = round((time.perf_counter() - started) * 1000)
        try:
            generated = json.loads(completion.output_text)
            answer = generated["answer"]
            cited_ids = tuple(generated["cited_evidence_ids"])
            if not isinstance(answer, str) or not answer.strip() or any(
                    not isinstance(value, str) for value in cited_ids):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("model returned malformed grounded answer") from exc
        validated = resolve_citations(
            evidence, cited_ids, allowed_person_ids=set(person_ids),
            scope_token=request.scope_token, resolver=self._resolver)
        cited_people = {row.person_id for row in validated}
        people = tuple(hit.person for hit in hits if hit.person.person_id in cited_people)
        trace = (ModelTrace(
            Capability.DEEP.value, completion.provider, completion.model_alias, latency,
            completion.input_tokens, completion.output_tokens, completion.request_id),)
        return encode_answer_response(AnswerResponse(
            answer.strip(), people, validated, cited_ids,
            {"query": request.question, "grounded": True}, trace))
