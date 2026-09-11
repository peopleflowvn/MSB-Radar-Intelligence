from __future__ import annotations

import os
from typing import Sequence

from .engine import RetrievalRecord, normalize_text


class HaystackBM25Ranker:
    """Request-local BM25 reference adapter over already-authorized records."""

    def rank(self, query: str, records: Sequence[RetrievalRecord]) -> Sequence[tuple[str, float]]:
        if not records or not normalize_text(query):
            return ()
        os.environ.setdefault("HAYSTACK_TELEMETRY_ENABLED", "false")
        try:
            from haystack import Document
            from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
            from haystack.document_stores.in_memory import InMemoryDocumentStore
        except ImportError as exc:  # pragma: no cover - optional dependency environment
            raise RuntimeError("Haystack BM25 requires the 'haystack' optional dependency") from exc

        query_tokens = set(normalize_text(query).split())
        eligible = []
        for record in records:
            content = normalize_text(" ".join((record.chunk.person.display_name or "", record.chunk.evidence.text)))
            if query_tokens & set(content.split()):
                eligible.append((record, content))
        if not eligible:
            return ()

        store = InMemoryDocumentStore(shared=False)
        store.write_documents([
            Document(
                id=record.chunk.evidence.evidence_id,
                content=content,
            )
            for record, content in eligible
        ])
        result = InMemoryBM25Retriever(store, top_k=len(eligible), scale_score=False).run(
            query=normalize_text(query)
        )["documents"]
        return tuple((document.id, float(document.score)) for document in result if document.score and document.score > 0)
