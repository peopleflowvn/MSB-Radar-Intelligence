from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class RetrievalMetrics:
    cases: int
    recall_at_k: float
    precision_at_k: float
    mean_reciprocal_rank: float


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
        if not expected:
            raise ValueError("evaluation truth must contain at least one relevant person")
        top = list(actual[:k])
        relevant = sum(person_id in expected for person_id in top)
        recalls.append(relevant / len(expected))
        precisions.append(relevant / k)
        rank = next((position for position, person_id in enumerate(top, start=1) if person_id in expected), None)
        reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
    count = len(expected_and_actual)
    return RetrievalMetrics(
        cases=count,
        recall_at_k=sum(recalls) / count,
        precision_at_k=sum(precisions) / count,
        mean_reciprocal_rank=sum(reciprocal_ranks) / count,
    )
