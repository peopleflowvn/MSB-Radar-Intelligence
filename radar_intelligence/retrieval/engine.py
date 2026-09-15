from __future__ import annotations

import re
import unicodedata
from math import sqrt
from dataclasses import dataclass
from typing import Protocol, Sequence

from radar_intelligence.contracts import SearchFilters, SearchHit, SearchRequest

from .hybrid import CandidateChunk, group_and_fuse


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    plain = "".join(character for character in decomposed if unicodedata.category(character) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def _values(values: Sequence[str]) -> set[str]:
    return {normalize_text(value) for value in values if normalize_text(value)}


@dataclass(frozen=True)
class RetrievalRecord:
    chunk: CandidateChunk
    locations: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()
    education: tuple[str, ...] = ()
    years_experience: float | None = None
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True)
class RetrievalScope:
    allowed_person_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not self.allowed_person_ids:
            raise ValueError("retrieval scope must contain at least one authorized person")


class SemanticRanker(Protocol):
    def rank(self, query: str, records: Sequence[RetrievalRecord]) -> Sequence[tuple[str, float]]: ...


class LexicalRanker(Protocol):
    def rank(self, query: str, records: Sequence[RetrievalRecord]) -> Sequence[tuple[str, float]]: ...


class NullSemanticRanker:
    def rank(self, query: str, records: Sequence[RetrievalRecord]) -> Sequence[tuple[str, float]]:
        return ()


class QueryEmbedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


_EMPTY_PREPARED_MATRIX = ((), (), None)


class CosineSemanticRanker:
    def __init__(self, embedder: QueryEmbedder, candidate_limit: int = 1_000) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")
        self._embedder = embedder
        self._candidate_limit = candidate_limit
        # (key, ids, matrix) swapped in one assignment so a concurrent rank()
        # call on another thread never observes an ids/matrix pair rebuilt
        # from two different index revisions.
        self._prepared: tuple = _EMPTY_PREPARED_MATRIX

    @property
    def _prepared_key(self) -> tuple[str, ...]:
        return self._prepared[0]

    @property
    def _prepared_ids(self) -> tuple[str, ...]:
        return self._prepared[1]

    @property
    def _prepared_matrix(self):
        return self._prepared[2]

    @staticmethod
    def _document_matrix(records, np):
        grouped = {}
        for record in records:
            if record.embedding is not None:
                document_id = record.chunk.evidence.document_id
                grouped.setdefault(document_id, []).append(record)
        identifiers = tuple(rows[0].chunk.evidence.evidence_id for rows in grouped.values())
        matrix = np.asarray([
            np.mean(np.asarray([row.embedding for row in rows], dtype=np.float32), axis=0)
            for rows in grouped.values()
        ], dtype=np.float32)
        return identifiers, matrix

    def prepare(self, records: Sequence[RetrievalRecord]) -> None:
        """Build the immutable production vector matrix once per index revision."""
        embedded = [(record.chunk.evidence.evidence_id, record.embedding)
                    for record in records if record.embedding is not None]
        key = tuple(identifier for identifier, _ in embedded)
        if key == self._prepared[0]:
            return
        try:
            import numpy as np
        except ImportError:  # pragma: no cover - minimal installations
            self._prepared = _EMPTY_PREPARED_MATRIX
            return
        ids, matrix = self._document_matrix(records, np)
        self._prepared = (key, ids, matrix)

    def rank(self, query: str, records: Sequence[RetrievalRecord]) -> Sequence[tuple[str, float]]:
        query_rows = self._embedder.embed_documents([query])
        if len(query_rows) != 1 or not query_rows[0]:
            raise ValueError("query embedder returned an invalid vector")
        query_vector = tuple(float(value) for value in query_rows[0])
        embedded = [(record.chunk.evidence.evidence_id, record.embedding)
                    for record in records if record.embedding is not None]
        if not embedded:
            return ()
        if any(len(vector) != len(query_vector) for _, vector in embedded):
            raise ValueError("query and document embedding dimensions differ")
        try:
            import numpy as np
        except ImportError:  # pragma: no cover - minimal installations
            scores = []
            query_norm = sqrt(sum(value * value for value in query_vector))
            for evidence_id, vector in embedded:
                denominator = query_norm * sqrt(sum(value * value for value in vector))
                score = (0.0 if denominator == 0 else
                         sum(a * b for a, b in zip(query_vector, vector)) / denominator)
                scores.append((evidence_id, score))
            return scores

        # Production indexes contain tens of thousands of chunk vectors. NumPy
        # performs the same bounded cosine calculation in native code instead
        # of holding the request thread in millions of Python-level operations.
        prepared = self._prepared
        key = tuple(identifier for identifier, _ in embedded)
        if key != prepared[0] or prepared[2] is None:
            self.prepare(records)
            prepared = self._prepared
        matrix = prepared[2]
        identifiers = prepared[1]
        query_array = np.asarray(query_vector, dtype=np.float32)
        denominators = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_array)
        dots = matrix @ query_array
        values = np.divide(dots, denominators, out=np.zeros_like(dots), where=denominators != 0)
        limit = min(self._candidate_limit, len(values))
        if limit == len(values):
            selected = np.arange(len(values))
        else:
            selected = np.argpartition(values, -limit)[-limit:]
        ordered = selected[np.argsort(values[selected])[::-1]]
        return tuple((identifiers[int(index)], float(values[index])) for index in ordered)


def _structured_match(record: RetrievalRecord, filters: SearchFilters) -> tuple[bool, float]:
    checks: list[bool] = []
    if filters.locations:
        checks.append(bool(_values(record.locations) & _values(filters.locations)))
    if filters.skills_all:
        checks.append(_values(filters.skills_all) <= _values(record.skills))
    if filters.companies:
        checks.append(bool(_values(record.companies) & _values(filters.companies)))
    if filters.education:
        checks.append(bool(_values(record.education) & _values(filters.education)))
    if filters.min_years_experience is not None:
        checks.append(record.years_experience is not None and record.years_experience >= filters.min_years_experience)
    if filters.max_years_experience is not None:
        checks.append(record.years_experience is not None and record.years_experience <= filters.max_years_experience)
    if filters.excluded_terms:
        searchable = normalize_text(" ".join((record.chunk.evidence.text,) + record.companies))
        if any(normalize_text(term) in searchable for term in filters.excluded_terms):
            return False, 0.0
    if checks and not all(checks):
        return False, 0.0
    return True, (sum(checks) / len(checks) if checks else 0.0)


def _lexical_scores(query: str, records: Sequence[RetrievalRecord]) -> dict[str, float]:
    query_tokens = set(normalize_text(query).split())
    if not query_tokens:
        return {}
    scores: dict[str, float] = {}
    for record in records:
        text = " ".join((record.chunk.person.display_name or "", record.chunk.evidence.text))
        tokens = set(normalize_text(text).split())
        overlap = len(query_tokens & tokens)
        if overlap:
            scores[record.chunk.evidence.evidence_id] = overlap / len(query_tokens)
    return scores


class TokenOverlapRanker:
    def rank(self, query: str, records: Sequence[RetrievalRecord]) -> Sequence[tuple[str, float]]:
        return tuple(_lexical_scores(query, records).items())


def _rank_map(scores: dict[str, float]) -> dict[str, int]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return {identifier: rank for rank, (identifier, _) in enumerate(ordered, start=1)}


class HybridRetriever:
    def __init__(
        self,
        semantic_ranker: SemanticRanker | None = None,
        lexical_ranker: LexicalRanker | None = None,
    ) -> None:
        self._semantic_ranker = semantic_ranker or NullSemanticRanker()
        self._lexical_ranker = lexical_ranker or TokenOverlapRanker()

    def search(
        self,
        request: SearchRequest,
        records: Sequence[RetrievalRecord],
        scope: RetrievalScope,
    ) -> tuple[SearchHit, ...]:
        # Scope is enforced before structured, lexical or semantic components.
        authorized = [record for record in records if record.chunk.person.person_id in scope.allowed_person_ids]
        filtered: list[tuple[RetrievalRecord, float]] = []
        for record in authorized:
            matches, score = _structured_match(record, request.filters)
            if matches:
                filtered.append((record, score))

        candidates = [record for record, _ in filtered]
        lexical_scores = dict(self._lexical_ranker.rank(request.query, tuple(candidates)))
        allowed_evidence = {record.chunk.evidence.evidence_id for record in candidates}
        if any(identifier not in allowed_evidence for identifier in lexical_scores):
            raise ValueError("lexical ranker returned evidence outside its authorized input")
        lexical_ranks = _rank_map(lexical_scores)
        semantic_scores = dict(self._semantic_ranker.rank(request.query, tuple(candidates)))
        if any(identifier not in allowed_evidence for identifier in semantic_scores):
            raise ValueError("semantic ranker returned evidence outside its authorized input")
        semantic_ranks = _rank_map(semantic_scores)

        fused = []
        for record, structured_score in filtered:
            evidence_id = record.chunk.evidence.evidence_id
            lexical_rank = lexical_ranks.get(evidence_id)
            semantic_rank = semantic_ranks.get(evidence_id)
            if lexical_rank is None and semantic_rank is None and structured_score == 0:
                continue
            fused.append(CandidateChunk(
                person=record.chunk.person,
                evidence=record.chunk.evidence,
                lexical_rank=lexical_rank,
                semantic_rank=semantic_rank,
                structured_score=structured_score,
            ))
        return group_and_fuse(fused, request.limit)
