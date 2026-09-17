# Brain V2 — conditional counts and population coverage

Date: 2026-09-08. Local continuation; production acceptance remains NOT MEASURED.

The old count branch skipped evidence reading and supplied an FTS union as a population estimate. Six new regression tests reproduced this before the implementation (5 failures, 1 error). The continuation now evaluates conditional counts through existing retrieval/judge stages and labels the measured subset and unknown coverage. Only the supported unconditional SQL population count is exact.

## Runtime changes

- Planner treats every membership condition, including negation, as mandatory for counts; previous-result names remain scope.
- Count judge returns SUPPORTED / CONTRADICTED / UNKNOWN per condition. Code requires a complete schema, valid source passage and complete matching quote for each supported condition; thoa=true cannot override UNKNOWN. An explicit-absence condition also requires an explicit negative quote; a skill list or a statement of missing information cannot support it. Malformed rows use the existing partial retry path. Criterion decisions remain model inferences, not verified semantic truth.
- Count totals are independent of displayed list length. A failed reader yields unknown matches rather than a false zero. JSON and SSE use deterministic count prose; SSE still executes subsequent requested steps.
- Applicant eligibility is enforced before count evaluation. Corpus CV/index/chunk counts use the same population. Field coverage includes applicants without TalentProfile; duplicate array values count once per person. Experience bucket labels state their boundaries.
- Conditional counts bypass the existing cross-request cache until its route/plan/eligibility version contract is improved. Per-request dossier reuse remains. Existing GreenNode task routes and schema/storage architecture are preserved.

## Live measurements

Four questions repeated three times using live GreenNode qwen/qwen3.6-flash on the existing six fictional CVs. Real planner, SQLite retrieval, judge, aggregation and answer composition; no production or dense-vector acceptance claim.

| Case | First evidence-review attempt: correct IDs | Final: correct IDs | Final: count and scope contract |
|---|---:|---:|---:|
| count_and | 3/3 | 3/3 | 3/3 |
| count_not | 3/3 | 3/3 | 3/3 |
| count_missing | 0/3 | 3/3 | 3/3 |
| count_subset | 3/3 | 3/3 | 3/3 |

count_missing deliberately has no proven match: SQL/Excel without a Python statement does not establish 'does not know Python'. The first live attempt returned that candidate incorrectly in all three runs despite a prompt warning. The criterion contract exposed UNKNOWN even when the overall model verdict said true; code rejects that contradiction. Later repeated calls also labelled the condition SUPPORTED with a SQL/Excel quote, requiring the additional polarity guard.

| Measurement across these 12 cold runs | First attempt | Final |
|---|---:|---:|
| P50 latency (ms) | 5060.57 | 8019.65 |
| P95 latency (ms) | 7713.08 | 14073.74 |
| Reported input tokens | 32491 | 34582 |
| Reported output tokens | 8607 | 12386 |

These are different validation contracts, sequential live runs and a tiny corpus; no causal speedup or production cost claim. The stricter contract spends output tokens to expose evidence gaps. Reported usage excludes unreported attempts; inspect raw tokens_complete flags.

## Regression checks

Affected ai + talent: 658 tests PASS in 103.295 s.
Subsequent baseline-manifest change: 10 focused tests PASS in 1.853 s. The count prompt now has its own version hash, so changing it cannot silently reuse a baseline context.

## Evidence and remaining work

- [First live attempt](brain_v2_counts_live.json): retained 3 false positives from missing negative evidence.
- [Additive-schema attempt](brain_v2_counts_verified.json) and [schema probe](brain_v2_counts_schema_probe.json): the model omitted the added field; initially mapped to UNKNOWN, then corrected to failed reads with retry.
- [Unified schema probe](brain_v2_counts_schema_fixed.json): supported AND and rejected unsupported NOT; [redundant overall-condition probe](brain_v2_counts_after.json) exposed missing overall-condition rows. Final schema uses atomic planner conditions, with the complete need as context.
- [Atomic-condition run](brain_v2_counts_final.json) exposed names incorrectly conjoined as criteria; [scope correction run](brain_v2_counts_acceptance.json) exposed explicit false support labels for absent evidence.
- [Final raw run](brain_v2_counts_guarded.json) records answers, trace, source ownership, criterion verdicts, model and runtime hashes. Failures are preserved; no historical results were overwritten.
- Semantic entailment and planner constraint completeness still need independent labels. SQL/Excel alone also cannot prove lack of Java; do not interpret model CONTRADICTED labels as hard negative facts. The Vietnamese/English polarity guard is a necessary check, not entailment validation: unrelated negations, complex wording and other languages still require evaluation. Partial CV passages and bounded retrieval cannot establish exact whole-store semantic counts.
- Next: audited structured predicates/materialized facts for exact supported conditions, stronger cache versioning, five-turn live HTTP/SSE acceptance, representative PostgreSQL corpus and human evidence review.

Reproduce locally with DATABASE_URL=sqlite:///:memory:, DEBUG=true, PYTHONUTF8=1:

```powershell
# From server; output must use a new filename for a new recorded run.
python manage.py brain_workflow_eval --model qwen/qwen3.6-flash --cases count_and,count_not,count_missing,count_subset --repeats 3 --out ../docs/benchmark/new_counts_run.json
python manage.py test ai talent --noinput --verbosity 1
# From repository root:
python scripts/brain_counts_summary.py
```
