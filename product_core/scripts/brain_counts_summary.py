"""Reproduce the conditional-count continuation report from recorded evidence."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "benchmark"


def read(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


before = read("brain_v2_counts_live.json")
after = read("brain_v2_counts_guarded.json")
lines = ["# Brain V2 — conditional counts and population coverage", "",
    "Date: 2026-09-08. Local continuation; production acceptance remains NOT MEASURED.", "",
    "The old count branch skipped evidence reading and supplied an FTS union as a population estimate. "
    "Six new regression tests reproduced this before the implementation (5 failures, 1 error). "
    "The continuation now evaluates conditional counts through existing retrieval/judge stages and labels "
    "the measured subset and unknown coverage. Only the supported unconditional SQL population count is exact.", "",
    "## Runtime changes", "",
    "- Planner treats every membership condition, including negation, as mandatory for counts; previous-result names remain scope.",
    "- Count judge returns SUPPORTED / CONTRADICTED / UNKNOWN per condition. Code requires a complete schema, "
    "valid source passage and complete matching quote for each supported condition; thoa=true cannot override UNKNOWN. "
    "An explicit-absence condition also requires an explicit negative quote; a skill list or a statement of missing information cannot support it. "
    "Malformed rows use the existing partial retry path. Criterion decisions remain model inferences, not verified semantic truth.",
    "- Count totals are independent of displayed list length. A failed reader yields unknown matches rather than a false zero. "
    "JSON and SSE use deterministic count prose; SSE still executes subsequent requested steps.",
    "- Applicant eligibility is enforced before count evaluation. Corpus CV/index/chunk counts use the same population. "
    "Field coverage includes applicants without TalentProfile; duplicate array values count once per person. Experience bucket labels state their boundaries.",
    "- Conditional counts bypass the existing cross-request cache until its route/plan/eligibility version contract is improved. "
    "Per-request dossier reuse remains. Existing GreenNode task routes and schema/storage architecture are preserved.", "",
    "## Live measurements", "",
    "Four questions repeated three times using live GreenNode qwen/qwen3.6-flash on the existing six fictional CVs. "
    "Real planner, SQLite retrieval, judge, aggregation and answer composition; no production or dense-vector acceptance claim.", "",
    "| Case | First evidence-review attempt: correct IDs | Final: correct IDs | Final: count and scope contract |",
    "|---|---:|---:|---:|"]
for case in ("count_and", "count_not", "count_missing", "count_subset"):
    old = [r for r in before["rows"] if r["case"] == case]
    new = [r for r in after["rows"] if r["case"] == case]
    lines.append(f"| {case} | {sum(r.get('exact_ids') is True for r in old)}/{len(old)} | "
                 f"{sum(r.get('exact_ids') is True for r in new)}/{len(new)} | "
                 f"{sum(r.get('review_count_correct') is True for r in new)}/{len(new)} |")
lines += ["", "count_missing deliberately has no proven match: SQL/Excel without a Python statement does not establish 'does not know Python'. "
          "The first live attempt returned that candidate incorrectly in all three runs despite a prompt warning. "
          "The criterion contract exposed UNKNOWN even when the overall model verdict said true; code rejects that contradiction. "
          "Later repeated calls also labelled the condition SUPPORTED with a SQL/Excel quote, requiring the additional polarity guard.", "",
          "| Measurement across these 12 cold runs | First attempt | Final |", "|---|---:|---:|"]
for label, key in (("P50 latency (ms)", "p50_ms"), ("P95 latency (ms)", "p95_ms")):
    lines.append(f"| {label} | {before['summary'][key]:.2f} | {after['summary'][key]:.2f} |")
for label, key in (("Reported input tokens", "input_tokens"), ("Reported output tokens", "output_tokens")):
    values = [sum(r.get("trace", {}).get("usage", {}).get(key) or 0 for r in report["rows"]) for report in (before, after)]
    lines.append(f"| {label} | {values[0]} | {values[1]} |")
lines += ["", "These are different validation contracts, sequential live runs and a tiny corpus; no causal speedup or production cost claim. "
          "The stricter contract spends output tokens to expose evidence gaps. Reported usage excludes unreported attempts; inspect raw tokens_complete flags.", "",
          "## Regression checks", ""]
log = ROOT / "brain-counts-complete-tests.log"
match = re.search(r"Ran (\d+) tests in ([\d.]+)s\s+OK", log.read_text(encoding="utf-8", errors="replace")) if log.exists() else None
lines.append(f"Affected ai + talent: {match[1]} tests PASS in {match[2]} s." if match else "Affected ai + talent: NOT MEASURED (final run missing or failed).")
manifest_log = ROOT / "brain-counts-manifest-tests.log"
manifest_check = re.search(r"Ran (\d+) tests in ([\d.]+)s\s+OK", manifest_log.read_text(encoding="utf-8", errors="replace")) if manifest_log.exists() else None
lines.append(f"Subsequent baseline-manifest change: {manifest_check[1]} focused tests PASS in {manifest_check[2]} s. "
             "The count prompt now has its own version hash, so changing it cannot silently reuse a baseline context."
             if manifest_check else "Count-prompt manifest verification: NOT MEASURED.")
lines += ["", "## Evidence and remaining work", "",
    "- [First live attempt](brain_v2_counts_live.json): retained 3 false positives from missing negative evidence.",
    "- [Additive-schema attempt](brain_v2_counts_verified.json) and [schema probe](brain_v2_counts_schema_probe.json): "
    "the model omitted the added field; initially mapped to UNKNOWN, then corrected to failed reads with retry.",
    "- [Unified schema probe](brain_v2_counts_schema_fixed.json): supported AND and rejected unsupported NOT; "
    "[redundant overall-condition probe](brain_v2_counts_after.json) exposed missing overall-condition rows. "
    "Final schema uses atomic planner conditions, with the complete need as context.",
    "- [Atomic-condition run](brain_v2_counts_final.json) exposed names incorrectly conjoined as criteria; "
    "[scope correction run](brain_v2_counts_acceptance.json) exposed explicit false support labels for absent evidence.",
    "- [Final raw run](brain_v2_counts_guarded.json) records answers, trace, source ownership, criterion verdicts, model and runtime hashes. "
    "Failures are preserved; no historical results were overwritten.",
    "- Semantic entailment and planner constraint completeness still need independent labels. SQL/Excel alone also cannot prove lack of Java; "
    "do not interpret model CONTRADICTED labels as hard negative facts. The Vietnamese/English polarity guard is a necessary check, "
    "not entailment validation: unrelated negations, complex wording and other languages still require evaluation. "
    "Partial CV passages and bounded retrieval cannot establish exact whole-store semantic counts.",
    "- Next: audited structured predicates/materialized facts for exact supported conditions, stronger cache versioning, "
    "five-turn live HTTP/SSE acceptance, representative PostgreSQL corpus and human evidence review.", "",
    "Reproduce locally with DATABASE_URL=sqlite:///:memory:, DEBUG=true, PYTHONUTF8=1:", "",
    "```powershell", "# From server; output must use a new filename for a new recorded run.",
    "python manage.py brain_workflow_eval --model qwen/qwen3.6-flash --cases count_and,count_not,count_missing,count_subset --repeats 3 --out ../docs/benchmark/new_counts_run.json",
    "python manage.py test ai talent --noinput --verbosity 1", "# From repository root:", "python scripts/brain_counts_summary.py", "```", ""]
(DATA / "BRAIN_V2_COUNTS.md").write_text("\n".join(lines), encoding="utf-8")
