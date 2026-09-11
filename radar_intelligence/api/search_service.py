from __future__ import annotations

from pathlib import Path

from radar_intelligence.api.codec import encode_search_hit
from radar_intelligence.auth import RadarScopeConfig, RadarScopeValidator
from radar_intelligence.config import RuntimeSettings
from radar_intelligence.indexing import SqliteDocumentIndex
from radar_intelligence.providers import GreenNodeConfig, GreenNodeEmbedder
from radar_intelligence.retrieval import (
    CosineSemanticRanker, HybridRetriever, RetrievalScope, project_search_documents,
)


class SearchService:
    def __init__(self, settings: RuntimeSettings, database: str | Path) -> None:
        if not settings.ready:
            raise ValueError("runtime settings are incomplete")
        values = settings.values
        self._scope = RadarScopeValidator(RadarScopeConfig(
            values["RADAR_BASE_URL"], values["RADAR_SERVICE_TOKEN"]))
        embedder = GreenNodeEmbedder(
            GreenNodeConfig(values["GREENNODE_BASE_URL"], values["GREENNODE_API_KEY"]),
            values["GREENNODE_MODEL_EMBEDDING"],
        )
        self._retriever = HybridRetriever(CosineSemanticRanker(embedder))
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
