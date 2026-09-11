from __future__ import annotations

from dataclasses import dataclass

from radar_intelligence.contracts import Evidence, PersonRef, SearchHit


@dataclass(frozen=True)
class CandidateChunk:
    person: PersonRef
    evidence: Evidence
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    structured_score: float = 0.0


def _rrf(rank: int | None, k: int = 60) -> float:
    return 0.0 if rank is None else 1.0 / (k + rank)


def group_and_fuse(chunks: list[CandidateChunk], limit: int = 10) -> tuple[SearchHit, ...]:
    """Reference reciprocal-rank fusion grouped by Person.

    This intentionally keeps policy simple. Production weights and reranking
    must be selected by evaluation, not by intuition.
    """
    grouped: dict[str, list[tuple[float, CandidateChunk]]] = {}
    for chunk in chunks:
        if chunk.evidence.person_id != chunk.person.person_id:
            raise ValueError("chunk evidence belongs to another person")
        raw = _rrf(chunk.lexical_rank) + _rrf(chunk.semantic_rank) + 0.02 * max(0, min(1, chunk.structured_score))
        grouped.setdefault(chunk.person.person_id, []).append((raw, chunk))

    hits: list[SearchHit] = []
    max_raw = (2 / 61) + 0.02
    for items in grouped.values():
        items.sort(key=lambda pair: (-pair[0], pair[1].evidence.evidence_id))
        person_score = min(1.0, items[0][0] / max_raw)
        best_evidence = tuple(pair[1].evidence for pair in items[:3])
        matched = ("structured",) if any(pair[1].structured_score > 0 for pair in items) else ()
        hits.append(SearchHit(items[0][1].person, person_score, best_evidence, matched))
    hits.sort(key=lambda hit: (-hit.score, hit.person.person_id))
    return tuple(hits[:limit])
