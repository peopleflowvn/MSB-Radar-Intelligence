"""Versioned synthetic gold and deterministic architecture contracts.

No LLM grades another LLM here. Missing measurements remain None. Contract
probes call real business functions; controlled model JSON is adversarial input,
not a replacement used to claim live model quality.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

GOLD_PATH = Path(__file__).with_name("fixtures") / "brain_v2_gold.json"


def gold_set():
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def retrieval_metrics(expected, actual, k=10):
    """Unique IDs; precision denominator is returned slots up to K.

    Recall of an empty gold set is undefined; no-result accuracy is separate.
    Duplicate returned IDs do not earn extra credit and consume result slots.
    """
    expected = set(expected)
    slots = list(actual)[:k]
    hits = len(expected & set(slots))
    return {"recall_at_k": hits / len(expected) if expected else None,
            "precision_at_k": hits / len(slots) if slots else None,
            "no_result_correct": not slots if not expected else None,
            "duplicates": len(slots) - len(set(slots))}


def percentile(values, p):
    values = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v))
    if not values:
        return None
    index = (len(values) - 1) * p
    lo, hi = math.floor(index), math.ceil(index)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def contract_results():
    from talent.answer import aggregate, cache, judge, plan, verify
    from talent.answer.retrieve import Candidate, Passage

    query = plan.QueryPlan(information_need="SQL, bắt buộc không Python",
                           must_have=["SQL", "không Python"], search_queries=["SQL"],
                           next_steps=[{"shape": "action", "yeu_cau": "soạn nháp"}])
    candidate = Candidate(1, "Fixture An", passages=[Passage(
        1, 11, 0, "Kỹ năng SQL tại Hà Nội. Có 5 năm kinh nghiệm.")])

    def parse(row):
        return judge._parse_batch(json.dumps({"ket_qua": [row]}), [candidate], query)

    def row(**overrides):
        value = {"id": 1, "thoa": True, "do_tin": .9,
                 "trich_dan": [{"doan": 1, "nguyen_van": "Kỹ năng SQL tại Hà Nội."}]}
        value.update(overrides)
        return value

    def context(ids):
        return SimpleNamespace(projection=SimpleNamespace(
            last_result={"items": [{"id": i} for i in ids]}))

    checks = {
        "widen_preserves_hard_constraints": lambda: plan.widen(query).must_have == query.must_have,
        "widen_preserves_next_steps": lambda: plan.widen(query).next_steps == query.next_steps,
        "ordinal_cache_order": lambda: cache._context_marker(context([1, 2])) != cache._context_marker(context([2, 1])),
        "json_false_is_not_true": lambda: not any(j.relevant for j in parse(row(thoa="false"))),
        "boolean_id_is_not_integer_id": lambda: not parse(row(id=True)),
        "unverified_cannot_qualify": lambda: not aggregate.aggregate(query, parse(row(trich_dan=[])))[0],
        "nan_confidence_not_high": lambda: judge._num(float("nan")) == 0,
        "infinite_confidence_not_high": lambda: judge._num(float("inf")) == 0,
        "duplicate_judge_ids": lambda: len(judge._parse_batch(json.dumps({"ket_qua": [row(), row()]}), [candidate], query)) <= 1,
        "malformed_extraction_safe": lambda: isinstance(parse(row(boc_duoc=[1])), list),
        "malformed_citations_safe": lambda: isinstance(parse(row(trich_dan=42)), list),
        "unknown_citation_detected": lambda: bool(verify.check(query, parse(row()), "Fixture An phù hợp [999].", [])),
        "partial_batch_detected": lambda: not judge._read_batch(query, [candidate, Candidate(2, "Fixture Bình")],
            lambda *a, **k: SimpleNamespace(text=json.dumps({"ket_qua": [row()]}), truncated=False))[1],
        "malformed_next_steps_safe": lambda: plan._next_steps(42) == [],
    }
    results = []
    for name, check in checks.items():
        started = time.perf_counter()
        try:
            passed, error = bool(check()), ""
        except Exception as exc:  # failure is evidence, not a harness crash
            passed, error = False, type(exc).__name__
        results.append({"case": name, "passed": passed, "error": error,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3)})
    return results


def contract_report():
    rows = contract_results()
    return {"suite": "deterministic_contracts", "gold_version": gold_set()["version"],
            "measurement_scope": "local real business functions; no live model or retrieval quality claim",
            "passed": sum(r["passed"] for r in rows), "total": len(rows), "cases": rows,
            "live_quality": None, "input_tokens": None, "output_tokens": None,
            "cost_per_query": None}
