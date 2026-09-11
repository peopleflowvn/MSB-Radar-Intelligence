from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from radar_intelligence.contracts import Evidence, PersonRef, SearchRequest
from radar_intelligence.evaluation import evaluate_retrieval
from radar_intelligence.retrieval import CandidateChunk, HaystackBM25Ranker, HybridRetriever, RetrievalRecord, RetrievalScope


def _record(person: dict) -> RetrievalRecord:
    person_id = str(person["id"])
    body = str(person["text"])
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return RetrievalRecord(CandidateChunk(
        person=PersonRef(person_id, str(person["name"])),
        evidence=Evidence(
            f"fixture-{person_id}", person_id, f"fixture-doc-{person_id}", "legacy-synthetic-fixture",
            body, "fixture text", 1.0, digest, "1",
        ),
    ))


def run(fixture_path: Path, k: int = 10, legacy_report_path: Path | None = None, lexical: str = "token") -> dict:
    raw = fixture_path.read_bytes()
    fixture = json.loads(raw.decode("utf-8"))
    records = tuple(_record(person) for person in fixture["people"])
    scope = RetrievalScope(frozenset(record.chunk.person.person_id for record in records))
    if lexical not in {"token", "haystack-bm25"}:
        raise ValueError("unsupported lexical ranker")
    retriever = HybridRetriever(lexical_ranker=HaystackBM25Ranker() if lexical == "haystack-bm25" else None)
    rows = []
    pairs = []
    for case in fixture["cases"]:
        if "queries" not in case or "expected_ids" not in case:
            continue
        query = " ".join(str(value) for value in case["queries"])
        started = time.perf_counter()
        hits = retriever.search(SearchRequest(query, "synthetic-scope", "benchmark", limit=k), records, scope)
        latency_ms = (time.perf_counter() - started) * 1000
        actual = [hit.person.person_id for hit in hits]
        expected = {str(value) for value in case["expected_ids"]}
        pairs.append((expected, actual))
        rows.append({"case": case["id"], "query": query, "expected_ids": sorted(expected), "actual_ids": actual,
                     "latency_ms": round(latency_ms, 3)})
    metrics = evaluate_retrieval(pairs, k)
    latencies = sorted(row["latency_ms"] for row in rows)

    def percentile(fraction: float) -> float | None:
        if not latencies:
            return None
        return latencies[round((len(latencies) - 1) * fraction)]

    report = {
        "suite": f"legacy_synthetic_fixture_v2_{lexical}",
        "fixture_sha256": hashlib.sha256(raw).hexdigest(),
        "fixture_truth_kind": fixture.get("truth_kind"),
        "k": k,
        "metrics": metrics.__dict__,
        "p50_ms": percentile(0.5),
        "p95_ms": percentile(0.95),
        "semantic_retrieval": "NOT MEASURED",
        "production_acceptance": "NOT MEASURED",
        "cases": rows,
    }
    if legacy_report_path is not None:
        legacy_raw = legacy_report_path.read_bytes()
        legacy = json.loads(legacy_raw.decode("utf-8"))
        report["legacy_comparison"] = {
            "report_sha256": hashlib.sha256(legacy_raw).hexdigest(),
            "suite": legacy.get("suite"),
            "macro_recall_at_10": legacy.get("macro_recall_at_10"),
            "macro_precision_at_10": legacy.get("macro_precision_at_10"),
            "p50_ms": legacy.get("p50_ms"),
            "p95_ms": legacy.get("p95_ms"),
            "scope": legacy.get("scope"),
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--legacy-report", type=Path)
    parser.add_argument("--lexical", choices=("token", "haystack-bm25"), default="token")
    args = parser.parse_args()
    report = run(args.fixture, args.k, args.legacy_report, args.lexical)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
