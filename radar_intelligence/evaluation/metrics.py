from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class RetrievalMetrics:
    cases: int
    retrieval_cases: int
    no_result_cases: int
    recall_at_k: float
    precision_at_k: float
    mean_reciprocal_rank: float
    no_result_accuracy: float | None


def evaluate_retrieval(
    expected_and_actual: Sequence[tuple[set[str], Sequence[str]]],
    k: int,
) -> RetrievalMetrics:
    if k <= 0:
        raise ValueError("k must be positive")
    if not expected_and_actual:
        raise ValueError("at least one evaluation case is required")
    recalls = []
    precisions = []
    reciprocal_ranks = []
    for expected, actual in expected_and_actual:
        top = list(actual[:k])
        if not expected:
            continue
        relevant = sum(person_id in expected for person_id in top)
        recalls.append(relevant / len(expected))
        precisions.append(relevant / len(top) if top else 0.0)
        rank = next((position for position, person_id in enumerate(top, start=1) if person_id in expected), None)
        reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
    count = len(expected_and_actual)
    no_result = [(not actual[:k]) for expected, actual in expected_and_actual if not expected]
    retrieval_count = len(recalls)
    return RetrievalMetrics(
        cases=count,
        retrieval_cases=retrieval_count,
        no_result_cases=len(no_result),
        recall_at_k=sum(recalls) / retrieval_count if retrieval_count else 0.0,
        precision_at_k=sum(precisions) / retrieval_count if retrieval_count else 0.0,
        mean_reciprocal_rank=sum(reciprocal_ranks) / retrieval_count if retrieval_count else 0.0,
        no_result_accuracy=(sum(no_result) / len(no_result) if no_result else None),
    )
