"""Rescore recorded probes; no inference calls and no changes to raw evidence."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "benchmark"
raw = json.loads((DATA / "brain_v2_models_probe.json").read_text(encoding="utf-8"))
conversation = json.loads((DATA / "brain_v2_conversation_probe.json").read_text(encoding="utf-8"))
rows = [row for row in raw["rows"] if row["task_probe"] != "conversation"]
rows += conversation["rows"]
new_models = json.loads((DATA / "brain_v2_new_models_probe.json").read_text(encoding="utf-8"))
rows += new_models["rows"]
tool_calls = json.loads((DATA / "brain_v2_tool_calls.json").read_text(encoding="utf-8"))
rows += tool_calls["rows"]
for row in rows:
    checks = row["checks"]
    if row["task_probe"] == "plan" and checks.get("fallback"):
        checks["pipeline_shape_correct"] = checks.get("shape_correct")
        checks["shape_correct"] = False
    if row["task_probe"] == "judge" and checks.get("read_incomplete"):
        checks["exact_ids"] = False
        if checks.get("no_result_correct") is not None:
            checks["no_result_correct"] = False

def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * p
    low = int(pos)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (pos - low)

def passes(row):
    c = row["checks"]
    if row["error"] or any(not call["ok"] or call.get("truncated") for call in row["calls"]):
        return False
    if row["task_probe"] == "plan":
        return c.get("shape_correct") and c.get("next_step_correct") is not False
    if row["task_probe"] == "judge":
        return c.get("exact_ids") and not c.get("read_incomplete")
    if row["task_probe"] == "intent":
        return c.get("intent_correct")
    if row["task_probe"] == "extraction":
        return c.get("sql_extracted") and not c.get("parse_failed")
    if row["task_probe"] == "compose":
        return c.get("cited") and c.get("names_expected_person") and not c.get("fallback")
    if row["task_probe"] == "vision":
        return c.get("ocr_exact_fields")
    if row["task_probe"] == "tool_call":
        return c.get("tool_call_correct")
    return c.get("has_answer", False)

summary = []
for model in dict.fromkeys(row["model"] for row in rows):
    for task in sorted({row["task_probe"] for row in rows if row["model"] == model}):
        samples = [r for r in rows if r["model"] == model and r["task_probe"] == task]
        calls = [call for r in samples for call in r["calls"]]
        summary.append({"model": model, "task": task, "n": len(samples),
            "contract_success": sum(bool(passes(row)) for row in samples),
            "attempts": len(calls), "errors": sum(not c["ok"] for c in calls),
            "truncated": sum(bool(c.get("truncated")) for c in calls),
            "p50_ms": round(percentile([r["latency_ms"] for r in samples], .5), 2),
            "p95_ms": round(percentile([r["latency_ms"] for r in samples], .95), 2),
            "known_input_tokens": sum(c["input_tokens"] or 0 for c in calls),
            "known_output_tokens": sum(c["output_tokens"] or 0 for c in calls),
            "unknown_usage_attempts": sum(c["input_tokens"] is None for c in calls)})
report = {"scorer_version": 2, "sources": ["brain_v2_models_probe.json", "brain_v2_conversation_probe.json", "brain_v2_new_models_probe.json", "brain_v2_tool_calls.json"],
          "corrections": ["Original conversation harness passed a tuple instead of ModelRequest; rerun replaces all seven invalid probes.",
                          "Fallback plan is not model intent success. Incomplete judge is not no-result success.",
                          "Contract success also requires no failed/truncated attempts; source quote existence is not semantic entailment."],
          "summary": summary, "rows": rows, "cost": None, "human_acceptance": None}
(DATA / "brain_v2_models_scored.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
lines = ["# GreenNode model benchmark — Brain V2", "",
    "Dates: 2026-09-07 to 2026-09-08. Live provider calls, fictional gold v1. **Small task probes, not production acceptance.**",
    "No saved task routes, provider settings or credentials were changed. The original run discovered seven models;",
    "the conversation rerun discovered ten. Two newly listed GLM models received the remaining 14 probes each;",
    "bge-m3 is an embedding model and its initial conversation failure is not an embedding benchmark.", "",
    "## Method and audit trail", "",
    "105 initial probes (7 models × 15 cases across 8 task groups). Seven conversation probes failed in the harness",
    "before calling a model: build_conversation_request returns a tuple. Corrected and reran conversation against",
    "the newly returned inventory. Raw evidence is retained; corrected scoring is in brain_v2_models_scored.json.",
    "Fallback plan output is not credited as model accuracy. Missing judge rows are a failed completeness contract,",
    "even when an empty returned list happens to match expected_ids=[]. Retries count as attempts and tokens.", "",
    "Actual plan/judge/extraction/compose/conversation code and prompts were used. Intent uses the runtime rubric",
    "to isolate model classification from provider-independent guards. Outreach and vision are isolated template",
    "probes (draft text and a tiny synthetic PNG), not full messaging/scanned-CV acceptance. No real messages were sent.",
    "The first run predates numeric-provenance/telemetry additions. Eight later Qwen Flash/Plus judge probes",
    "are retained separately in brain_v2_judge_after.json (all eight exact-ID contracts passed). They do not",
    "establish semantic entailment or a production-quality gain. No default changed from this small sample.", "",
    "`Pass` below means the narrow machine-checkable task contract completed without failed/truncated attempts.",
    "It does not measure all semantic correctness. n=1 P50=P95 is one observation, not a production percentile.",
    "Token totals include only reported usage; failed attempts may have unreported billing. Cost: **NOT MEASURED**.", "",
    "## Results by task", ""]
for task in sorted({s["task"] for s in summary}):
    lines += [f"### {task}", "", "| Model | Pass/n | Attempts/errors/cut | P50/P95 ms | Known input/output tokens | Unknown usage |",
              "|---|---:|---:|---:|---:|---:|"]
    for s in summary:
        if s["task"] == task:
            lines.append(f"| {s['model']} | {s['contract_success']}/{s['n']} | {s['attempts']}/{s['errors']}/{s['truncated']} | {s['p50_ms']}/{s['p95_ms']} | {s['known_input_tokens']}/{s['known_output_tokens']} | {s['unknown_usage_attempts']} |")
    lines.append("")
lines += ["## Conditional-count continuation", "",
    "Repeated live Qwen 3.6 Flash count workflows exposed both semantic false positives and schema omissions. "
    "[Continuation report](benchmark/BRAIN_V2_COUNTS.md) records the stricter evidence contract, remaining risks and measured token/latency cost. "
    "These are separate probes, not additions to the original 145-row model comparison; task defaults remain unchanged.", "",
    "## Routing recommendation", "",
    "- FAST plan/judge/extraction: retain Qwen 3.6 Flash as the existing default; Qwen 3.6 Plus is a candidate override. The probes support feasibility, not a universal winner.",
    "- DEEP compose: keep the configured DeepSeek V4 Pro route pending a broader difficult-comparison/composition gold set. One source-backed answer cannot establish best prose quality.",
    "- Tight output budgets: do not move FAST/conversation/outreach to DeepSeek by default; measured truncation/fallback behavior is workload dependent.",
    "- VISION: Qwen 3.6 Flash/Plus transcribed the fixture fields. Require real scanned-CV multilingual/OCR evaluation before claiming scan accuracy. A model appearing in /models does not establish vision capability.",
    "- EMBEDDING: retain current specialized model and index dimensions. No dense retrieval/cost comparison measured here. The newly listed bge-m3 was encountered in an unfiltered conversation inventory probe; its chat failure says nothing about embedding quality.",
    "- Tool calling: nine single-call probes use the actual evidence tool schema and 900-token agent budget; correctness requires the expected function and ordinal-resolved ID. This measures protocol only. Actual handler permissions/selection and multi-turn SSE persistence are covered separately by regression tests.", "",
    "## Remaining evaluation work", "",
    "Human-labelled production IDs and semantic evidence entailment; real PostgreSQL Recall@K; end-to-end HTTP/SSE follow-up chain; repeated cold/warm token and latency measurements; cost rate card; embedding comparison; tool-call protocol; real scanned CVs. Gold case coverage is not the same as executed acceptance coverage.", ""]
(ROOT / "docs" / "AI_MODEL_BENCHMARK.md").write_text("\n".join(lines), encoding="utf-8")
print(f"Scored {len(rows)} probes into {len(summary)} model/task rows.")
