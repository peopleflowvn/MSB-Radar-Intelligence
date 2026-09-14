"""Live, provider-pinned task probes. Never edits routing or sends real CVs."""
from __future__ import annotations

import base64
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from ai.brain_eval import gold_set, percentile, retrieval_metrics


def run_probe(kind, case, caller):
    from ai.adapter import RouterAdapter
    from ai.brain_eval import gold_set
    from ai.jsonx import extract_json
    from ai.projection import Projection
    from talent.answer import compose, judge, plan
    from talent.answer.retrieve import Candidate, Passage
    gold = gold_set()
    adapter = RouterAdapter(complete_fn=caller)
    envelope = SimpleNamespace(projection=Projection(last_result={"items": [
        {"id": pid, "name": next(p["name"] for p in gold["people"] if p["id"] == pid)}
        for pid in case.get("context_ids", [])]}))
    if kind == "plan":
        result = plan.plan(case["q"], envelope=envelope, complete_fn=caller)
        expected = case.get("allowed_shapes", [case.get("shape")])
        return {"shape_correct": result.shape in expected and not result.fallback,
                "pipeline_shape_correct": result.shape in expected, "fallback": result.fallback,
                "next_step_correct": (any(s["shape"] == case["next_step_shape"] for s in result.next_steps)
                                      if "next_step_shape" in case else None),
                "shape": result.shape}
    if kind == "judge":
        query = plan.QueryPlan(information_need=case["q"], must_have=case.get("must_have", []),
                               extract=["số năm kinh nghiệm", "năm sinh"])
        pool = [Candidate(p["id"], p["name"], passages=[Passage(p["id"], p["id"], 0, p["text"])])
                for p in gold["people"]]
        result = judge.judge(query, pool, complete_fn=caller, workers=1)
        from talent.answer.aggregate import aggregate
        chosen, _, _ = aggregate(query, result)
        ids = [j.person_id for j in chosen]
        metrics = retrieval_metrics(case["expected_ids"], ids, 10)
        if result.incomplete and not case["expected_ids"]:
            metrics["no_result_correct"] = False
        return {"ids": ids, "exact_ids": not result.incomplete and set(ids) == set(case["expected_ids"]),
                "read_incomplete": result.incomplete,
                **metrics,
                "verified_source_quotes": sum(e.get("exact", False) for j in chosen for e in j.evidence),
                "evidence_count": sum(len(j.evidence) for j in chosen)}
    if kind == "extraction":
        from intel.extraction import _ai_extract
        result, usage = _ai_extract(gold["people"][0]["text"], ["skills", "city"], adapter)
        values = result.get("skills", {})
        values = values.get("value", []) if isinstance(values, dict) else values
        return {"sql_extracted": "SQL" in str(values), "parse_failed": bool(usage.get("parse_failed"))}
    if kind == "compose":
        p = gold["people"][0]
        j = judge.Judgement(p["id"], p["name"], True, .9, "Có kỹ năng SQL",
                            evidence=[{"document_id": 1, "ordinal": 0, "quote": "Kỹ năng SQL, Python, Power BI."}])
        text, used, _, meta = compose.compose(plan.QueryPlan(information_need="Ai biết SQL?"),
            [j], [], {"judged": 1, "retrieved": 1}, complete_fn=caller)
        return {"cited": bool(used), "names_expected_person": p["name"] in text,
                "fallback": meta["fallback"], "answer_correctness": None}
    if kind == "conversation":
        from ai.conversation import build_conversation_request
        request, _flags = build_conversation_request("Giải thích ngắn transferable skills là gì")
        response = adapter.complete(request)
        return {"has_answer": bool(response.text.strip()), "answer_correctness": None}
    if kind == "intent":
        from ai.intent import _RUBRIC, _coerce
        response = caller([{"role": "system", "content": _RUBRIC},
                           {"role": "user", "content": case["q"]}],
                          task="assistant_intent", temperature=0, max_tokens=180,
                          response_format={"type": "json_object"})
        payload = extract_json(response.text)
        parsed = _coerce(payload) if isinstance(payload, dict) else None
        expected = "web" if case.get("requires_web") else "search"
        return {"intent_correct": bool(parsed and parsed.kind == expected)}
    if kind == "tool_call":
        from ai.toolset import TOOLS
        spec = TOOLS["read_allowed_evidence"]
        result = caller([
            {"role": "system", "content": "Bạn là Radar. Để đọc hồ sơ, gọi đúng tool được cấp; không đoán bằng chứng."},
            {"role": "user", "content": "Đọc bằng chứng người thứ hai. Danh sách theo thứ tự: Fixture Chi (person_id=3), Fixture An (person_id=1), Fixture Bình (person_id=2)."}],
            task="assistant_agent", max_tokens=900, temperature=.2, reasoning_effort="none",
            tools=[{"type": "function", "function": {"name": "read_allowed_evidence",
                    "description": spec["description"], "parameters": spec["parameters"]}}])
        message = ((result.raw.get("choices") or [{}])[0].get("message") or {})
        calls = message.get("tool_calls") or []
        good = False
        if len(calls) == 1:
            function = calls[0].get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
                good = (function.get("name") == "read_allowed_evidence"
                        and type(arguments.get("person_id")) is int and arguments["person_id"] == 1)
            except (ValueError, AttributeError):
                pass
        return {"tool_call_correct": good, "scope": "protocol and ordinal only; no tool execution"}
    if kind == "outreach":
        # Isolated template probe: avoid handler DB/identity side effects. Report
        # separately from full draft_outreach workflow acceptance.
        response = caller([{"role": "system", "content": "Soạn nháp lời mời phỏng vấn tiếng Việt, không gửi. Chỉ dùng dữ kiện được cung cấp."},
                           {"role": "user", "content": "Fixture An biết SQL. Vị trí Data Analyst ở Hà Nội. Không biết email hoặc thời gian phỏng vấn."}],
                          task="assistant_outreach", temperature=.2, max_tokens=700, reasoning_effort="none")
        return {"has_answer": bool(response.text.strip()), "workflow_acceptance": None}
    if kind == "vision":
        from PIL import Image, ImageDraw
        picture = Image.new("RGB", (600, 180), "white")
        ImageDraw.Draw(picture).text((20, 30), "Fixture: AN\nExperience: 5 years\nSkill: SQL", fill="black")
        data = io.BytesIO()
        picture.save(data, format="PNG")
        url = "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()
        response = caller([{"role": "user", "content": [
            {"type": "text", "text": "Transcribe only the text in this image."},
            {"type": "image_url", "image_url": {"url": url}}]}],
            task="cv_ocr", max_tokens=500, reasoning_effort="none")
        return {"ocr_exact_fields": all(t in response.text.lower() for t in ("an", "5", "sql")),
                "scanned_cv_acceptance": None}
    raise ValueError(kind)


class Command(BaseCommand):
    help = "Live cross-provider task probes on fictional data; no saved route changes."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True)
        parser.add_argument("--models", default="")
        parser.add_argument("--providers", default="greennode",
                            help="Configured providers to compare, comma-separated.")
        parser.add_argument("--tasks", default="")
        parser.add_argument("--repeats", type=int, default=1)
        parser.add_argument("--workers", type=int, default=2)
        parser.add_argument("--timeout", type=int, default=30)

    def handle(self, *args, **options):
        from ai.providers import OpenAICompatibleProvider, list_models
        from ai.router import Router
        router = Router(sink=None)
        provider_names = list(dict.fromkeys(
            value.strip().lower() for value in options["providers"].split(",")
            if value.strip()))
        if not provider_names:
            raise CommandError("At least one provider is required.")
        targets, discovered = [], {}
        for provider_name in provider_names:
            prototype = router.get_provider(provider_name)
            if prototype is None:
                discovered[provider_name] = {"configured": False, "models": []}
                continue
            prototype.timeout = options["timeout"]
            if provider_name == "greennode":
                available = list_models(prototype)
                models = (options["models"].split(",") if options["models"] else
                          (available if len(provider_names) == 1 else [prototype.model]))
                if any(model not in available for model in models):
                    raise CommandError("Requested model not in live GreenNode model listing.")
            else:
                models = [prototype.model]
            discovered[provider_name] = {"configured": True, "models": models}
            targets.extend((provider_name, model, prototype) for model in models)
        if not targets:
            raise CommandError("No requested provider has runtime credentials; benchmark NOT MEASURED.")
        if not 1 <= options["repeats"] <= 10 or not 1 <= options["workers"] <= 4:
            raise CommandError("Use repeats 1..10, workers 1..4.")
        by_id = {c["id"]: c for c in gold_set()["cases"]}
        cases = [("plan", by_id[i]) for i in ("unaccented", "not", "ordinal", "multi")]
        cases += [("judge", by_id[i]) for i in ("and", "semantic", "injection", "empty")]
        cases += [("intent", by_id[i]) for i in ("mixed", "web")]
        cases += [(kind, {"id": kind}) for kind in ("extraction", "compose", "conversation", "outreach", "vision")]
        if "tool_call" in options["tasks"].split(","):
            cases.append(("tool_call", {"id": "tool_call"}))
        if options["tasks"]:
            requested = set(options["tasks"].split(","))
            if requested - {kind for kind, _case in cases}:
                raise CommandError("Unknown task probe.")
            cases = [(kind, case) for kind, case in cases if kind in requested]
        jobs = [(provider, model, prototype, kind, case, rep)
                for rep in range(options["repeats"])
                for provider, model, prototype in targets for kind, case in cases]
        def work(job):
            provider_name, model, prototype, kind, case, rep = job
            provider = OpenAICompatibleProvider(provider_name, prototype.base_url,
                prototype.api_key, model, timeout=options["timeout"],
                extra_headers=prototype.extra_headers)
            calls = []
            def caller(messages, task="", **kwargs):
                kwargs.pop("budget_seconds", None)
                kwargs["timeout"] = options["timeout"]
                start = time.perf_counter()
                entry = {"task": task, "provider": provider_name, "model": model,
                         "input_tokens": None, "output_tokens": None, "error": ""}
                try:
                    result = provider.complete(messages, **kwargs)
                    entry.update(input_tokens=result.prompt_tokens, output_tokens=result.completion_tokens,
                                 truncated=result.truncated, ok=True)
                    return result
                except Exception as exc:
                    entry.update(ok=False, error=type(exc).__name__)
                    raise
                finally:
                    entry["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
                    calls.append(entry)
            started = time.perf_counter()
            try:
                checks, error = run_probe(kind, case, caller), ""
            except Exception as exc:
                checks, error = {}, type(exc).__name__
            finally:
                close_old_connections()
            return {"provider": provider_name, "model": model,
                    "task_probe": kind, "case": case["id"], "repeat": rep,
                    "checks": checks, "error": error, "calls": calls,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
        rows = []
        output = Path(options["out"])
        output.parent.mkdir(parents=True, exist_ok=True)
        report = {"scorer_version": 2,
                  "scope": "Live task probes on synthetic fixture v1; not production/human acceptance. Outreach and vision are isolated template probes.",
                  "providers": discovered, "repeats": options["repeats"],
                  "saved_routes_changed": False, "cost": None, "rows": rows}
        with ThreadPoolExecutor(max_workers=options["workers"]) as pool:
            for future in as_completed([pool.submit(work, job) for job in jobs]):
                row = future.result()
                rows.append(row)
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                self.stdout.write(f"{len(rows)}/{len(jobs)} {row['model']} {row['task_probe']} {row['error'] or row['checks']}")
                self.stdout.flush()
        summary = []
        for provider_name, model, _prototype in targets:
            for kind in sorted({k for k, _c in cases}):
                samples = [r for r in rows if r["provider"] == provider_name
                           and r["model"] == model and r["task_probe"] == kind]
                calls = [c for r in samples for c in r["calls"]]
                summary.append({"provider": provider_name, "model": model,
                    "task": kind, "n": len(samples), "attempts": len(calls),
                    "errors": sum(not c.get("ok") for c in calls),
                    "p50_ms": percentile([r["latency_ms"] for r in samples], .5),
                    "p95_ms": percentile([r["latency_ms"] for r in samples], .95),
                    "input_tokens": sum(c["input_tokens"] for c in calls if c["input_tokens"] is not None),
                    "output_tokens": sum(c["output_tokens"] for c in calls if c["output_tokens"] is not None)})
        report["summary"] = summary
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
