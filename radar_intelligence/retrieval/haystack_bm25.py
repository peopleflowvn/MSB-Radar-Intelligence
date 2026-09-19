from __future__ import annotations

import os
from typing import Sequence

from .engine import RetrievalRecord, normalize_text

_EMPTY_PREPARED = ((), (), None, {})


class HaystackBM25Ranker:
    """Haystack BM25 over an already-authorized lexical candidate set.

    `candidate_limit` is a safety CEILING, not a routine truncation: the
    production corpus is documented to hold tens of thousands of chunks
    (see retrieval/engine.py), and structured filters are the mechanism for
    narrowing scope, not this bound. A hard cap of 1000 here previously
    silently limited real lexical search to an arbitrary ~1000 chunks
    (sorted by evidence_id, i.e. effectively random) out of the whole
    authorized corpus for any account whose candidate pool exceeded that —
    everyone else was permanently invisible to BM25 regardless of query.
    Default is raised well above any corpus size seen in production so it
    only bites as an actual circuit breaker, not a day-to-day filter.
    """

    def __init__(self, candidate_limit: int = 100_000, rank_limit: int = 1_000) -> None:
        if candidate_limit < 1 or rank_limit < 1:
            raise ValueError("candidate_limit and rank_limit must be positive")
        self._candidate_limit = candidate_limit
        # How many top-scoring chunks a query returns. Haystack materialises every
        # returned Document through to_dict/from_dict; returning the whole corpus
        # (66k chunks in production, Sept 2026) cost ~2.7 s per query versus
        # ~0.7 s for the top 1000, and ranks beyond that contribute ~nothing to
        # reciprocal-rank fusion (1/(60+1000)).
        self._rank_limit = rank_limit
        # (key, prepared_records, retriever, tokens_by_id) swapped in one
        # assignment so a concurrent rank() call on another thread never
        # observes a retriever built from one candidate set paired with a
        # mismatched key.
        self._prepared: tuple = _EMPTY_PREPARED

    @property
    def _prepared_key(self) -> tuple[str, ...]:
        return self._prepared[0]

    @property
    def _prepared_records(self):
        return self._prepared[1]

    def prepare(self, records: Sequence[RetrievalRecord]) -> None:
        key = tuple(sorted(record.chunk.evidence.evidence_id for record in records))
        if key == self._prepared[0]:
            return
        prepared_records = tuple(
            (record, content, frozenset(content.split()))
            for record, content in (
                (record, normalize_text(" ".join(
                    (record.chunk.person.display_name or "", record.chunk.evidence.text))))
                for record in records
            )
        )
        # Bound corpus size independent of the query text: preselecting by
        # query-token overlap before indexing would make BM25's term-frequency
        # statistics vary per question instead of reflecting one stable corpus,
        # which corrupts scores rather than just bounding cost.
        bounded = tuple(sorted(
            prepared_records, key=lambda row: row[0].chunk.evidence.evidence_id
        ))[:self._candidate_limit]
        retriever = self._build_retriever(bounded, self._rank_limit)
        tokens_by_id = {
            record.chunk.evidence.evidence_id: tokens for record, _, tokens in prepared_records
        }
        self._prepared = (key, prepared_records, retriever, tokens_by_id)

    @staticmethod
    def _build_retriever(bounded, rank_limit=1_000):
        os.environ.setdefault("HAYSTACK_TELEMETRY_ENABLED", "false")
        try:
            from haystack import Document
            from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
            from haystack.document_stores.in_memory import InMemoryDocumentStore
        except ImportError as exc:  # pragma: no cover - optional dependency environment
            raise RuntimeError("Haystack BM25 requires the 'haystack' optional dependency") from exc
        store = InMemoryDocumentStore(shared=False)
        store.write_documents([
            Document(id=record.chunk.evidence.evidence_id, content=content)
            for record, content, _ in bounded
        ])
        return InMemoryBM25Retriever(store, top_k=max(1, min(len(bounded), rank_limit)),
                                     scale_score=False)

    def rank(self, query: str, records: Sequence[RetrievalRecord]) -> Sequence[tuple[str, float]]:
        query_tokens = set(normalize_text(query).split())
        if not records or not query_tokens:
            return ()
        prepared = self._prepared
        key = tuple(sorted(record.chunk.evidence.evidence_id for record in records))
        if key != prepared[0]:
            self.prepare(records)
            prepared = self._prepared
        retriever = prepared[2]
        tokens_by_id = prepared[3]
        result = retriever.run(query=normalize_text(query))["documents"]
        # Some BM25 variants (Haystack's included) assign length-normalized
        # documents a small nonzero score even with zero query-term overlap.
        # The corpus/IDF stats above stay query-independent (the correctness
        # fix); this only keeps that smoothing noise out of the result set.
        return tuple(
            (document.id, float(document.score))
            for document in result
            if document.score and document.score > 0
            and query_tokens & tokens_by_id.get(document.id, frozenset())
        )
