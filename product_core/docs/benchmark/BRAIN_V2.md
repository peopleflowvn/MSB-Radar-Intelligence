# Brain V2 evaluation protocol

Gold: `server/ai/fixtures/brain_v2_gold.json`, v1, 6 fictional people / 33
questions covering 32+ categories. Explicit fixture facts are synthetic truth;
leadership is labelled inference. These are not human-labelled production CVs.
Unknown and ambiguous cases must not be assigned invented labels.

From `server`, with PowerShell:

```powershell
$env:PYTHONUTF8='1'
$env:DEBUG='true'
$env:DATABASE_URL='sqlite:///:memory:'
python manage.py brain_eval --out ../docs/benchmark/brain_v2_contracts_after.json
python manage.py brain_retrieval_eval --out ../docs/benchmark/brain_v2_retrieval_after.json
python manage.py test ai.tests_brain_eval --noinput
```

`brain_eval` returns nonzero on contract failure; writes results before exiting.
The baseline contracts intentionally reproduce 14 discovered defects. 0/14 is
not overall AI accuracy: this is a targeted failure set, not a representative
sample. Harness tests separately guard metric denominators and gold integrity.

`brain_retrieval_eval` refuses persistent databases, migrates a process-local
in-memory database, then calls real retrieval/SQL/RRF/passages. No mock search.
Curated search expansions bypass planning deliberately to isolate retrieval.
SQLite has no dense branch. At K=10 on six people the test can reveal omissions,
but is too small to assess ranking at production scale. Broad retrieval precision
is not final answer precision. Blank structured profiles remain in the fixture.

Precision uses returned slots; duplicates consume slots but earn one hit.
Recall excludes empty expected sets (undefined); no-result correctness is
separate. Latency uses linear-interpolated empirical percentiles, with sample
size/scope stated. Missing live tokens/cost/evidence metrics remain null or
NOT MEASURED, never zero or 100% by default.

Failure taxonomy: constraint mutation; permissive JSON; unsupported facts;
missing/duplicate batch rows; context identity collision; unresolved reference;
invalid citation; surface divergence; missing observability; insufficient gold.
Before report is immutable; create a distinct after report.

## Live probes and reproducibility

`brain_model_benchmark` uses provider-pinned real GreenNode calls and the same
fictional gold. It never changes saved routes or sends real CVs. Main task
matrix and protocol-only tool calls are separate:

```powershell
python manage.py brain_model_benchmark --models qwen/qwen3.6-flash,qwen/qwen3.6-plus --out ../docs/benchmark/new_task_run.json
python manage.py brain_model_benchmark --models qwen/qwen3.6-flash --tasks tool_call --out ../docs/benchmark/new_tool_run.json
python manage.py brain_workflow_eval --model qwen/qwen3.6-flash --out ../docs/benchmark/new_workflow_run.json
python manage.py brain_workflow_eval --model qwen/qwen3.6-flash --cases unknown --repeats 3 --out ../docs/benchmark/new_identity_run.json
```

Keep `DATABASE_URL=sqlite:///:memory:` for workflow evaluation. It refuses a
persistent database or non-database cache, seeds the process-only corpus,
executes the real Answer Engine, and stores input/output token counts, source
checks, expected IDs, literal count/unknown checks and source-code hashes.
Do not overwrite the committed before/after evidence when rerunning; use a new
filename and report date/model/code hashes.

Artifacts intentionally retain intermediate failures:

- `brain_v2_workflow_probe.json`: reversed age order; source-check harness used
  a nonexistent `quote` key instead of `snippet`. Those source scores are invalid.
- `brain_v2_workflow_before_optimization.json`: matched cold/warm workload before
  arithmetic/coverage composition and dossier-reuse optimization.
- `brain_v2_workflow_routing_probe.json`: model emitted COUNT plus person SORT.
- `brain_v2_workflow_identity_probe.json`: model selected other people's birth
  years for a requested profile with missing data. Unknown case lacked a scorer
  originally; do not read its expected-ID subtotal as full answer correctness.
- `brain_v2_workflow_after.json`: final full sample; later direct-name fallback
  and shared HTTP bridge fixes have separate focused tests/probes.
- `brain_v2_identity_after.json`: three post-fix unknown cases, each reads one
  requested profile despite its blank derived normalized-name field.

`scripts/brain_model_summary.py` rescoring preserves raw observations and excludes
the invalid conversation harness run, fallback-plan credit and incomplete judge
credit. `scripts/brain_report.py` builds the final report from committed JSON;
test lines additionally use local ignored test logs. Missing logs produce NOT
MEASURED rather than reconstructing test success. No live model is used as the
sole judge. Source existence is not source entailment or human acceptance.

Production acceptance still needs: exported versioned source IDs and evidence
references, labels from a recruiter independent of implementation, permission
matrix, real PostgreSQL retrieval, HTTP/SSE multi-turn runs, cold/warm repeated
queries, per-attempt model telemetry and evidence entailment review. Do not
commit production CVs, PII, runtime DBs, API keys or raw conversation traces.

Conditional-count continuation: [BRAIN_V2_COUNTS.md](BRAIN_V2_COUNTS.md) records
the opt-in count_and/count_not/count_missing/count_subset scenarios, original
failures, schema/polarity/scope corrections, repeated live outputs and measured
cost in tokens/latency. The original workflow schedule and historical measurements
remain separate. Regenerate its summary with `python scripts/brain_counts_summary.py`.

Cache-validity continuation: [BRAIN_V2_CACHE.md](BRAIN_V2_CACHE.md) specifies the
data, execution and permission fingerprints, focused before/after contracts, local
query-count observation and remaining bulk-update/production limits.

Grounding continuation: [BRAIN_V2_GROUNDING.md](BRAIN_V2_GROUNDING.md) records the
source-assignment counterexamples, Unicode name-boundary fix, runtime/evaluation
telemetry and the still-unmeasured semantic-entailment boundary.
