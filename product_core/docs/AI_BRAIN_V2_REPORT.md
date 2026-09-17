# AI Brain V2 — report

Date: 2026-09-08. Source of truth: the existing local workspace.

**Engineering fixes and bounded synthetic evaluations are recorded below. Full production quality acceptance is NOT established.**
The final code through `f425cdb` was deployed to Hub and passed workflow health,
public HTTP health, CI, and a production configuration/embedding preflight. No pull,
reset, checkout, source replacement, production corpus migration or saved-route
change was performed. Deployment readiness is verified; recruiter-labelled answer
quality and production retrieval recall remain separate unmeasured gates.

## 1. BEFORE

See [baseline](AI_BRAIN_V2_BASELINE.md) for architecture, all 23 task routes/call sites, pipeline maps and evidence for the ten original root causes.
Baseline: 1,020 backend tests passed (313.387 s); frontend 11 files / 65 tests passed (60.06 s). Local read-only inventory had 8 People, 10 Documents, 14 ExtractedFacts, 1 MaterializedProfile, zero search documents/chunks. It cannot represent production retrieval.
The 14 deliberately selected defect probes all failed before fixes. This 0/14 is a counterexample set, not initial overall AI accuracy.

## 2. TOP ROOT CAUSES

1. Widening retrieval mutated hard requirements/exclusions and lost subsequent actions.
2. Permissive JSON converted string false/bool IDs/non-finite confidence into accepted judgements.
3. Numbers had no attribute-level provenance; arbitrary CV years became birth years or experience.
4. Missing/duplicate batch rows were treated as complete; retry reread already successful dossiers.
5. Cache normalized away displayed order and omitted relevant workflow context.
6. Pinning was mistaken for exact target resolution; ordinal/direct-name scope could expand to other people.
7. Citation syntax was mistaken for source validation; JSON/SSE repair behavior diverged.
8. Token/latency tracking omitted failures, parallel work and upstream assistant stages.
9. Existing acceptance tests lacked explicit IDs/denominators and could pass despite wrong live prose.
10. Repeated evidence reading and model composition of deterministic arithmetic inflated cost and introduced errors.
Live probes additionally exposed COUNT+SORT contradiction, reversed age direction, false absence for an existing profile, and incorrect coverage prose. The shared Assistant bridge also dropped revisions and ordered result state. These are documented in [change decisions](AI_BRAIN_V2_CHANGES.md).

## 3. CHANGES

Continuation: independent review export/scoring, projection v2 provenance/state audit, threaded response timeout handling and Settings windowed latency/failure metrics are implemented. See [review and operations evidence](benchmark/BRAIN_V2_REVIEW_OPERATIONS.md) for measured checks and explicit limits; these changes do not establish production acceptance.

Continuation: conditional counts now evaluate evidence per condition, preserve previous-result scope and publish reviewed/unknown coverage; corpus statistics use a consistent applicant population. [Conditional-count evidence and limitations](benchmark/BRAIN_V2_COUNTS.md) records repeated live failures, corrections and the latest regression run separately from the original eleven-case performance baseline.

Continuation: retrieval/judgement cache keys now bind the normalized executed plan, raw corpus identity/eligibility timestamps, effective plan/judge/embedding routes, prompt versions and current role/module scope. [Cache validity evidence](benchmark/BRAIN_V2_CACHE.md) records the pre-fix failures, focused checks, query-count cost and remaining bulk-update limitation.

Continuation: final-answer citations are now assigned to the nearby person claim using Unicode-safe name boundaries. [Citation assignment evidence](benchmark/BRAIN_V2_GROUNDING.md) records the counterexamples, trace/eval telemetry and the explicit semantic-entailment limit.

Preserve query constraints while broadening retrieval; strict unique batch rows, finite confidence and partial coverage; verify numeric FACT provenance and keep semantic attributes as INFERENCE/UNKNOWN; sort and count deterministically; verify citation membership/ownership; replace truncated/invalid answers with complete fallback.
Resolve displayed ordinals, direct full-name factual subjects and out-of-range references; constrain action tools to selected IDs and allowed surfaces. Preserve final revisions and ordered people across Assistant SSE requests. Public history/done omit chain-of-thought; internal retention remains unchanged.
Keep existing task overrides and introduce capability policy plus request trace. Reuse identical dossiers only within one request; a changed document/passages/criteria/source identity triggers rereading. Keep existing extraction/materialization rather than migrating to a second snapshot.
No consequential tool actions were added. Drafting remains a proposal; existing permissions, DNC/workflow/transaction guards and deferred HM/RM scope remain.

## 4. AFTER

- Original defect contracts: 14/14 PASS. Broad regression: 1047 tests PASS / 244.913 s.
- Final affected AI/Talent regression: 647 tests PASS / 93.143 s; final stream/identity bridge: 37 tests PASS / 27.217 s.
- Cache-validity continuation: focused 12 tests PASS / 1.033 s; current AI/Talent/Intel/People regression after cache changes: 799 tests PASS / 134.368 s.
- Citation-assignment continuation: focused 23 tests PASS / 6.313 s; current AI/Talent/Intel/People regression after grounding changes: 802 tests PASS / 121.517 s.
- Final frontend: 11 files / 72 tests PASS, 37.51 s. Concurrent unrelated Edge commit bfe9ca5 added frontend tests and is preserved; the higher frontend count is not attributed to Brain V2.
- Live full workflow: real plan/retrieve/judge/aggregate/compose on 6 fictional people, GreenNode Qwen 3.6 Flash pinned for the experiment only; 11 cold cases plus one warm repeat.
- Explicit expected-ID sets: 9/9; source excerpts: 8/8; exact total count and explicit unknown checks passed.
- A subsequent direct-name normalization fix was checked separately: 3/3 unknown-fact cases passed, each reading only the requested profile (including a blank derived normalized-name field). The full workflow timing below predates that final narrowing and the shared HTTP bridge correction; do not silently substitute the later samples into its percentiles.

Definition-of-Done evidence status:

| Deliverable | Status / practical limit |
|---|---|
| Baseline, architecture/AI-call maps, failure taxonomy | Recorded against local source |
| Gold set and eval harness | 33 fictional cases / 32+ tags; explicit fixture truth |
| Retrieval, evidence, follow-up metrics/tests | Measured locally; dense/production labels remain missing |
| Token, latency, before/after | Measured on matched synthetic workload; no production SLA/cost claim |
| GreenNode model benchmark and routing recommendation | 145 scored probes plus 8 judge reruns; defaults preserved |
| Regression/adversarial tests, weaknesses, updated docs | Recorded; see reproducibility protocol |
| Production answer correctness / hallucination / human acceptance | NOT MEASURED; cannot mark product acceptance complete |

Final operational evidence (2026-09-09): deploy run `34303643888` passed for exact
SHA `f425cdb`, including migration/container health; CI run `34303643821` passed Hub
on Python 3.9 and 3.11, web test/typecheck/lint/build, Agent test/lint/build and secret
scan. Public health returned HTTP 200. Preflight run `34304917969` confirmed
PostgreSQL with 1,075 people and 679 documents, enabled GreenNode/Gemini provider
configuration, and three Gemini embedding endpoints producing 1,536-dimensional
vectors. It did not inspect CV content or measure retrieval relevance.

## 5. INTENT METRICS

Final workflow shape agreement: 11/11 cold cases. This is a small plan-shape contract, not general intent accuracy. Model-by-task intent/plan results are in [model benchmark](AI_MODEL_BENCHMARK.md).
Keep failed intermediate runs: one model invocation reversed age ordering; a later one emitted COUNT with an explicit person sort. Deterministic consistency checks were added rather than switching the application to a stronger single model.

## 6. RETRIEVAL METRICS

| SQLite fallback, K=10 | Before | After |
|---|---:|---:|
| Macro Recall@10, nonempty truth cases | 1.0000 | 1.0000 |
| Macro Precision@10, returned-slot denominator | 0.6087 | 0.6087 |
| Retrieval P50 ms | 2.64 | 2.01 |
| Retrieval P95 ms | 5.633 | 2.403 |
Six people, curated query expansions, no dense index, K larger than corpus. This proves no observed fixture recall loss; it cannot prove production ranking quality or a speedup. SQL/FTS/pgvector acceptance on a representative labelled corpus: NOT MEASURED.

## 7. EVIDENCE METRICS

Final full workflow: 8/8 displayed source excerpts normalize to text in the source document owned by the displayed person. This is **source existence/ownership**, not semantic entailment, source truth, or hiring suitability. Quotes in a CV containing malicious instructions can exist without supporting a judgement.
Adversarial regressions cover invented citation IDs, unrelated/unverified quotes, malformed schema, unsupported numeric attributes, graduation-year confusion, negation, duplicate rows, missing rows and prompt injection. A blanket hallucination percentage is NOT MEASURED.

## 8. ANSWER QUALITY

Nine expected candidate sets, literal fixture count, explicit birth/experience statements and an unknown profile have machine-checkable truth. Free-form helpfulness, all-negative-claim grounding, semantic entailment and recruiter acceptance are not fully machine-verified.
Earlier prose contradicted valid ranks, falsely stated a profile was absent, or added irrelevant keyword counts. Supported numeric/coverage answers now come from code. Generic semantic synthesis stays with AI and retains known weaknesses below. Human Acceptance@K and broad answer correctness: NOT MEASURED.

## 9. FOLLOW-UP QUALITY

Tests cover displayed [3,1,2] order, second=[1], first-two=[3,1], previous-set filters, out-of-range, unknown identity, changed-cache context, selected tool ID guards and a two-request real HTTP/SSE bridge that persists corrected text and ordered state. The HTTP bridge test replaces the model boundary; it does not mock persistence/projection/endpoint logic under test.
Live ordinal probe selected the expected person and returned the explicit five-year fact. Tool-call protocol probes use the real evidence-tool schema and expected ordinal ID. Full five-turn live workflow through deployed UI, semantic pronoun ambiguity and recruiter acceptance: NOT MEASURED.

## 10. TOKEN BEFORE/AFTER

Matched 11 cold cases, same fictional corpus/model; one observational run each. Before means the intermediate pre-optimization implementation, not the untouched initial workspace. Prompts and model outputs vary, so total differences are not a controlled attribution experiment.

| Reported tokens, 11 cold queries | Before optimization | After | Change |
|---|---:|---:|---:|
| input_tokens | 50065 | 36738 | -26.6% |
| output_tokens | 10849 | 6801 | -37.3% |

| Case | Input before/after | Output before/after | Calls before/after |
|---|---:|---:|---:|
| empty | 6186/5361 | 2401/1130 | 4/4 |
| injection | 6200/4727 | 2266/1240 | 4/3 |
| oldest | 3229/1440 | 271/149 | 2/1 |
| youngest | 3227/1439 | 210/147 | 2/1 |
| most_exp | 3227/1441 | 253/156 | 2/1 |
| count | 3326/1440 | 237/112 | 2/1 |
| unknown | 6107/2894 | 1513/764 | 4/2 |

Warm repeated AND query: input 4402 → 3324; output 627 → 265; cache miss → hit. Existing cross-request caching already existed; this is its measured effect, not a newly invented cache feature.
No-result widening now reuses identical dossier judgements; exact arithmetic avoids compose calls. Later direct-name probes each read one profile and used 2,117–2,119 input tokens, versus six profiles before narrowing. Failed/unreported token usage remains unknown; public trace exposes tokens_complete. Cost/query and initial-workspace production token baseline: NOT MEASURED.

## 11. LATENCY BEFORE/AFTER

| 11 cold workflow cases | Before optimization | After |
|---|---:|---:|
| P50 ms | 8764.22 | 6050.65 |
| P95 ms | 16383.96 | 9643.51 |
Warm AND query: 6050.65 → 4432.04 ms. Subsequent direct-name probes: 2881.05, 2779.84, 3084.55 ms.
These percentiles summarize 11 different synthetic cases; no confidence interval, concurrent-load test or production tail-latency claim. Some individual queries were slower despite lower aggregate latency. Router timeout is bounded but multi-stage deadlines still lack hard cancellation.

## 12. GREENNODE MODEL BENCHMARK

[AI_MODEL_BENCHMARK.md](AI_MODEL_BENCHMARK.md) contains 145 scored task probes / 82 model-task rows plus eight separate Qwen judge reruns. Nine generative models were probed; bge-m3 appeared in a conversation inventory probe, which is not an embedding test. Workloads include intent, plan, extraction, judge, compose, conversation, outreach, synthetic vision and tool-call protocol.
Original harness failures are retained: seven conversation probes failed before the API call and were replaced with corrected runs; fallback plans and incomplete judge output do not earn success. The first workflow scorer read quote instead of the public snippet key; its source_checks are invalid and excluded. Later reports store actual source snippets and verify ownership independently.

## 13. CURRENT MODEL ROUTING

| Workload / task | Preserved route |
|---|---|
| Plan, judge, extraction, intent, conversation, agent/tools, JD, RB/Social tasks | GreenNode Qwen 3.6 Flash |
| talent_answer_compose | GreenNode DeepSeek V4 Pro |
| person_qa | GreenNode DeepSeek V4 Flash |
| cv_ocr | GreenNode Qwen 3.6 Flash |
| talent_embedding | Existing specialized Gemini embedding route |
FAST/DEEP/VISION/EMBEDDING are workload policies with per-task overrides, not a single-model switch. The live workflow deliberately pinned Flash to test the architecture on a cheaper model; it did not change business defaults. Actual deployment availability, encrypted settings and provider disable/bootstrap semantics need environment verification before rollout.

## 14. REMAINING WEAKNESSES

- Production data quality, true PostgreSQL/vector recall and evidence recall are unmeasured; local corpus is tiny and unindexed.
- Citation ownership is now checked within each person's local prose block and emitted in trace/eval telemetry. It still cannot prove semantic entailment. Near-miss explanations can contain unsupported negative assertions; numeric extraction covers only explicit formats and can reduce coverage.
- Conditional AND/NOT counts now report bounded evidence evaluations with unknown coverage, without an FTS population estimate. They remain INFERENCE, not exact whole-store semantic counts. Per-condition source checks and a polarity guard cannot prove full semantic entailment or planner completeness; see the continuation evidence.
- Full live multi-turn UI acceptance, ambiguous pronouns, authorization/PII review across every surface, and real scanned CV/embedding comparisons remain open.
- Cache now versions the normalized executed plan, effective routes, plan/judge prompts, applicant Person/Document/index state and current role/modules. Direct bulk SQL that bypasses timestamps/indexing can still evade it; plan/memory-rich keys may reduce hit rate. Production cache hit rate and latency are NOT MEASURED.
- Historical LLMCall schema represents missing tokens as integers; request trace reports unknowns separately. Streaming usage can be missing; no provider rate-card cost or hard cancellation SLA.
- Snapshot provenance is not uniformly queryable for every derived attribute. Existing ExtractedFact/MaterializedProfile must be extended incrementally, with truth labels, rather than duplicated.
- The current criteria/source/steps UI is preserved. Routing-profile redesign and broad observability UI are deferred until a representative quality gate is met.

## 15. WHAT NOT TO CHANGE BEFORE HACKATHON

Do not switch every task to one powerful model, shrink retrieval recall silently, remove raw CVs, introduce another snapshot schema, rewrite the agent/tool loop, delete still-reachable legacy paths, relax hard constraints or treat synthetic scores as recruiter acceptance. Keep GreenNode multi-model task overrides and existing human/action controls. No auto-send/merge/reject/claim transitions.

## 16. POST-HACKATHON ROADMAP

1. Version a representative authorized PostgreSQL corpus; obtain independent recruiter labels, disputed-case review and evidence spans. Include blank fields, scans, duplicated identities, updates and permission boundaries. This unlocks true Recall/Acceptance@K and error rates.
2. Extend existing intelligence materialization with explicit source/version/status and extraction eval; benchmark coverage/token benefit before migrating reads. Preserve raw CV and support re-extraction rollback.
3. Extend the bounded conditional-count implementation with validated structured predicates or audited materialized-fact queries for exact supported conditions. Preserve unknown coverage and independent semantic acceptance checks.
4. Run repeated live HTTP/SSE five-turn workflows, fault injection, concurrency/load and model/capability comparisons. Set budgets/canary thresholds from measured tails, token completeness and quality regression gates.
5. Add independently labelled source-entailment/hallucination audits, enforce timestamp/version discipline for bulk corpus mutations, then introduce simple routing profiles and observability UI. Human acceptance precedes promotion.

Reproduce using [evaluation protocol](benchmark/BRAIN_V2.md). Review [change decisions and rollback](AI_BRAIN_V2_CHANGES.md). No claim that the Talent/Assistant surfaces have passed full production acceptance.
