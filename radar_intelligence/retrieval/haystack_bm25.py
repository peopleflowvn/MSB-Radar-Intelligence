from __future__ import annotations

import os
from typing import Sequence

from .engine import RetrievalRecord, normalize_text


class HaystackBM25Ranker:
    """Haystack BM25 over a bounded, already-authorized lexical candidate set."""

    def __init__(self, candidate_limit: int = 1_000) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")
        self._candidate_limit = candidate_limit
        self._prepared_key: tuple[str, ...] = ()
        self._prepared_records = ()

    def prepare(self, records: Sequence[RetrievalRecord]) -> None:
        key = tuple(record.chunk.evidence.evidence_id for record in records)
        if key == self._prepared_key:
            return
        self._prepared_key = key
        prepared = []
        for record in records:
            content = normalize_text(" ".join(
                (record.chunk.person.display_name or "", record.chunk.evidence.text)))
            prepared.append((record, content, frozenset(content.split())))
        self._prepared_records = tuple(prepared)

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
        key = tuple(record.chunk.evidence.evidence_id for record in records)
        if key != self._prepared_key:
            self.prepare(records)
        eligible = []
        for record, content, content_tokens in self._prepared_records:
            overlap = len(query_tokens & content_tokens)
            if overlap:
                eligible.append((overlap, record, content))
        if not eligible:
            return ()

        # Building an in-memory Haystack store for every authorized chunk makes
        # a common query unbounded. This deterministic preselection preserves
        # scope and lexical relevance, then delegates final ordering to BM25.
        eligible.sort(key=lambda row: (-row[0], row[1].chunk.evidence.evidence_id))
        eligible = eligible[:self._candidate_limit]

        store = InMemoryDocumentStore(shared=False)
        store.write_documents([
            Document(
                id=record.chunk.evidence.evidence_id,
                content=content,
            )
            for _, record, content in eligible
        ])
        result = InMemoryBM25Retriever(store, top_k=len(eligible), scale_score=False).run(
            query=normalize_text(query)
        )["documents"]
        return tuple((document.id, float(document.score)) for document in result if document.score and document.score > 0)
