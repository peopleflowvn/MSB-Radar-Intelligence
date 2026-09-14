from __future__ import annotations


class RagasEvaluator:
    """Optional adapter for offline, sanitized grounded-answer benchmarks."""

    @staticmethod
    def evaluate(samples: list[dict], metrics: list) -> object:
        if not samples:
            raise ValueError("at least one evaluation sample is required")
        try:
            from ragas import EvaluationDataset, evaluate
        except ImportError as exc:
            raise RuntimeError(
                "Ragas is not installed; install the 'evaluation' extra") from exc
        dataset = EvaluationDataset.from_list(samples)
        return evaluate(dataset=dataset, metrics=metrics)
