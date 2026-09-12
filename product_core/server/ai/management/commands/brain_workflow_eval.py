"""Live Answer Engine acceptance probes on an ephemeral fictional corpus."""
import json
import hashlib
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from ai import telemetry
from ai.brain_eval import gold_set, percentile
from ai.projection import Projection
from ai.tasks import capability_for


class Command(BaseCommand):
    help = "Live plan/retrieve/judge/aggregate/compose; requires SQLite :memory:."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True)
        parser.add_argument("--model", required=True)
        parser.add_argument("--cases", default="")
        parser.add_argument("--repeats", type=int, default=1)

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        if db["ENGINE"] != "django.db.backends.sqlite3" or db["NAME"] != ":memory:":
            raise CommandError("Refusing persistent DB: use DATABASE_URL=sqlite:///:memory:.")
        if settings.CACHES["default"]["BACKEND"] != "django.core.cache.backends.db.DatabaseCache":
            raise CommandError("Requires database cache in the ephemeral SQLite DB.")
        from ai.providers import OpenAICompatibleProvider
        from ai.router import Router
        from ai.adapter import RouterAdapter
        from people.models import Document
        from talent.answer import engine
        from talent.vector_index import fold_text
        prototype = Router(sink=None).get_provider("greennode")
        if prototype is None:
            raise CommandError("GreenNode unavailable; NOT MEASURED.")
        output = Path(options["out"])
        output.parent.mkdir(parents=True, exist_ok=True)
        call_command("brain_retrieval_eval", out=str(output.with_name(output.stem + "_retrieval.json")))
        provider = OpenAICompatibleProvider("greennode", prototype.base_url,
            prototype.api_key, options["model"], timeout=25)
        judge_audit = []

        def caller(messages, task="", **kwargs):
            budget = kwargs.pop("budget_seconds", 25)
            kwargs["timeout"] = min(25, budget)
            started = time.perf_counter()
            entry = {"task": task, "provider": "greennode", "model": options["model"],
                     "capability": capability_for(task), "route_reason": "benchmark_override",
                     "ok": False, "error": "provider_failure"}
            try:
                result = provider.complete(messages, **kwargs)
                if task == "talent_answer_judge":
                    from ai.jsonx import extract_json
                    parsed = extract_json(result.text)
                    # Fictional in-memory corpus only; never retain hidden reasoning.
                    if isinstance(parsed, dict):
                        judge_audit.append({"rows": [{k: row[k] for k in
                            ("id", "thoa", "dieu_kien") if k in row}
                            for row in parsed.get("ket_qua", []) if isinstance(row, dict)]})
                entry.update(ok=True, error="", **telemetry.reported_usage(result))
                return result
            finally:
                entry["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                telemetry.record(entry)

        gold = gold_set()
        by_id = {case["id"]: case for case in gold["cases"]}
        # Opt-in continuation probes preserve the original eleven-case schedule.
        count_cases = [
            {"id": "count_and", "q": "Có bao nhiêu ứng viên biết cả SQL và Python?",
             "shape": "count", "expected_ids": [1], "review_count": 1, "scope_total": 6},
            {"id": "count_not", "q": "Có bao nhiêu ứng viên biết Java và chưa từng làm ngân hàng?",
             "shape": "count", "expected_ids": [3], "review_count": 1, "scope_total": 6},
            {"id": "count_missing", "q": "Có bao nhiêu ứng viên biết SQL và không biết Python?",
             "shape": "count", "expected_ids": [], "review_count": 0, "scope_total": 6},
            {"id": "count_subset", "q": "Trong số này có bao nhiêu người biết SQL?",
             "shape": "count", "context_ids": [3, 2], "expected_ids": [2],
             "review_count": 1, "scope_total": 2},
        ]
        by_id.update({case["id"]: case for case in count_cases})
        documents = {d.pk: d for d in Document.objects.all()}
        rows = []
        report = {"scope": "Live GreenNode, real engine/retrieval, 6 fictional people; SQLite fallback, no dense vectors. Model pinned for this experiment only.",
                  "model": options["model"], "gold_version": gold["version"], "rows": rows,
                  "cost": None, "human_answer_correctness": None, "production_acceptance": None}
        server = Path(__file__).resolve().parents[3]
        report["started_at"] = datetime.now(timezone.utc).isoformat()
        report["extra_case_definitions"] = count_cases
        report["runtime_sha256"] = {str(p.relative_to(server)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((server / "talent" / "answer").glob("*.py"))}
        # Adjacent repeated question measures cache effect, not pre-change speedup.
        schedule = [("and", False), ("and", True), ("exclusion", False),
                              ("semantic", False), ("injection", False), ("empty", False),
                              ("oldest", False), ("youngest", False), ("most_exp", False),
                              ("ordinal", False), ("unknown", False), ("count", False)]
        if options["cases"]:
            requested = set(options["cases"].split(","))
            schedule += [(case["id"], False) for case in count_cases]
            if requested - {case for case, warm in schedule}:
                raise CommandError("Unsupported workflow case.")
            schedule = [(case, warm) for case, warm in schedule if case in requested]
        if not 1 <= options["repeats"] <= 10:
            raise CommandError("Use repeats 1..10.")
        for case_id, warm in schedule * options["repeats"]:
            case = by_id[case_id]
            if not warm:
                cache.clear()  # Database cache resides in this ephemeral DB.
            envelope = SimpleNamespace(projection=Projection(last_result={"items": [
                {"id": pid, "name": next(p["name"] for p in gold["people"] if p["id"] == pid)}
                for pid in case.get("context_ids", [])]}))
            started = time.perf_counter()
            row = {"case": case_id, "warm": warm}
            judge_audit.clear()
            try:
                result = engine.answer(case["q"], envelope=envelope, complete_fn=caller,
                                       adapter=RouterAdapter(complete_fn=caller))
                ids = [p["person_id"] for p in result.people]
                verified = []
                for source in result.all_sources:
                    doc = documents.get(source.get("document_id"))
                    verified.append(bool(doc and doc.person_id == source.get("person_id")
                        and fold_text(source.get("snippet", ""))
                        and fold_text(source.get("snippet", "")) in fold_text(doc.best_text)))
                row.update(ids=ids, exact_ids=(set(ids) == set(case["expected_ids"])) if "expected_ids" in case else None,
                           shape=result.trace.get("plan", {}).get("shape"),
                           shape_correct=result.trace.get("plan", {}).get("shape") == case.get("shape"),
                           source_checks=verified, sources=result.all_sources, citations=len(result.sources),
                           answer=result.text, trace=result.trace,
                           numeric_attributes=[p.get("attributes", {}) for p in result.people], error="")
                if case.get("expected_unknown"):
                    row["unknown_fact_correct"] = (set(ids) <= set(case["target_ids"])
                        and not re.search(r"\b(?:19|20)\d{2}\b", result.text)
                        and "khong co ho so" not in fold_text(result.text)
                        and all(next(p["name"] for p in gold["people"] if p["id"] == pid) in result.text
                                for pid in case["target_ids"]))
                if "expected_count" in case:
                    row["exact_count_correct"] = re.findall(r"\d+", result.text) == [str(case["expected_count"])]
                if "review_count" in case:
                    measured = result.trace.get("count", {})
                    row["review_count_correct"] = (measured.get("matched") == case["review_count"]
                        and measured.get("scope_total") == case["scope_total"]
                        and measured.get("exact") is False
                        and "chưa xác định" in result.text)
            except Exception as exc:
                row["error"] = type(exc).__name__
            row["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            row["judge_criteria_audit"] = list(judge_audit)
            rows.append(row)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.stdout.write(f"{case_id} warm={warm} ids={row.get('ids')} error={row['error']}")
            self.stdout.flush()
        checks = [v for row in rows for v in row.get("source_checks", [])]
        cold = [r for r in rows if not r["warm"]]
        report["summary"] = {"runs": len(rows), "source_quotes_verified": sum(checks),
            "source_quotes_total": len(checks), "source_existence_accuracy": sum(checks) / len(checks) if checks else None,
            "shape_correct": sum(r.get("shape_correct", False) for r in cold), "shape_total": len(cold),
            "id_exact_correct": sum(r.get("exact_ids") is True for r in cold),
            "id_exact_total": sum(r.get("exact_ids") is not None for r in cold),
            "p50_ms": percentile([r["latency_ms"] for r in cold], .5),
            "p95_ms": percentile([r["latency_ms"] for r in cold], .95)}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
