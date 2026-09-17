# Brain V2 change decisions

## Phase 3 — intent and retrieval contracts

Problem/evidence: before probes prove `widen` removes hard exclusions and drops
next steps. Existing test even encodes that old behavior. Root cause: retrieval
expansion changes the definition of relevance. Fix: expand search queries only,
preserve all other QueryPlan fields. Expected gain: recall can expand without
admitting candidates that violate the user's request. Risk: fewer apparent
matches where old results were obtained by relaxing mandatory criteria.
The old test is renamed and corrected to the explicitly requested business
contract; it is not weakened to hide a runtime failure. New integration test
checks the actual judge payload retains exclusions and the subsequent action.

Problem/evidence: retrieve builds a pool large enough for pinned IDs but then
iterates `order[:pool]`, dropping remaining pins. Fix: deduplicate pins in order
and use the same bound for hydration and candidate construction. Expected gain:
explicitly referenced people remain readable. Risk: callers with many pins
cost more; existing pin limits remain. Test uses real People and a pool smaller
than the referenced set. No additional semantic filter or reduced pool budget.

## Phase 4 — snapshot decision

The synthetic fallback pool retains all expected people (Recall@10=1.0 on 19
nonempty cases; six-person corpus). This is not a cost benchmark of real CVs.
Existing ExtractedFact/MaterializedProfile already implement the durable layer.
Do not create a second snapshot model or run a data migration yet. Measure live
judge input and evidence completeness first; extend existing provenance later.

## Phase 5 — judge schema and partial failure

Evidence: contract before accepts string false, bool IDs, NaN, duplicate IDs,
malformed containers and partial batches; missing evidence still meets the
aggregate confidence floor. Fix strict JSON boundary, finite confidence, unique
batch indices, exact batch coverage, and retry missing dossiers only. Preserve
valid partial rows but mark incomplete, surface unread count and don't cache
partial results. Fallback passage is useful context but does not certify an
unsupported assertion; confidence stays below acceptance floor. Semantic
reasoning supported by verified quotes still qualifies. No keyword gate added.

Risks: weak JSON model outputs yield more visible unknowns/retries. Existing
quote/extraction tests remain; add adversarial contracts and partial retry tests.
Per-attribute semantic entailment remains a separate unresolved problem.

## Phase 6 — aggregate/compose validation

The actual source list now validates citation IDs and person ownership for
mentioned candidates. Both JSON compose and stream repair run the same check;
a repair that fails validation uses deterministic ordered fallback with source
numbers, rather than keeping a known wrong answer. Repeated truncated JSON
compose falls back regardless of visible character count. No new LLM judge.
The old valid-order test omitted sources because the verifier ignored them;
now it supplies the actual sources from its chosen fixtures (same expected
correct ordering). Semantic entailment is not proven by this check.

## Phase 7 — workflow cache identity

Preserve last-result order and hash relevant projection state (criteria,
patches, mentioned IDs, memories, summary, recent turns). Bump cache namespace
to invalidate results produced by the old judge/constraint policy. Expected
gain: no reuse across swapped ordinal targets or changed workflow intent.
Risk: lower hit rate when context changes; repeated stable input still reuses
the same key. Regression now checks ordinal selection, out-of-range references,
action-loop target guards and ordered state across two real HTTP/SSE requests.

## Live counterexamples — arithmetic, identity and composition

The first live workflow chose the youngest person for "oldest": planner emitted
birth-year DESC and the whole-store path obeyed it. Normalize unambiguous age
ordering using the requested objective; keep generic semantic intent with AI.
A later call emitted COUNT plus an explicit person sort/limit. Those contracts
contradict: a scalar count has no person ordering. Preserve the richer ranking
contract. Add the oldest/year direction to the plan prompt. No model replacement.

Whole-store extraction also used an arbitrary year as birth year and calendar
span as experience. Remove both estimates from factual ranking. Use explicit
affirmative source statements; graduation dates and negations remain unknown.
Locate the actual document containing the excerpt when a person has several CVs.
Risk: numeric coverage falls for formats not yet supported; expose that coverage,
retain raw CV, use existing reviewed extraction rather than inventing values.

Live prose contradicted valid top IDs, misrepresented missing coverage as an
execution failure and invented a new count aside. Render supported total-count
questions and whole-store numeric rankings deterministically, with known/total
coverage and source citations. The later conditional-count continuation below
closes the unsafe FTS-estimate path; exact semantic population counts remain open.
No raw 4,000-character output slicing: model output already has a token budget.
Repeated truncation, interrupted compose and invalid repair produce a complete
fallback; SSE revision replaces the earlier fragment.

Live named-person questions returned other people's known birth years when the
requested profile had no year. Resolve a direct full-name factual subject to an
explicit pool, distinct from semantic "people like X" searches. Validate actual
display names and handle blank normalized-name fields from manual imports.
An existing profile with insufficient evidence cannot be described as absent.
Duplicate names remain multiple candidates, never an automatic identity merge.

## Phase 7 — shared stream bridge and public output

Assistant SSE previously dropped engine revisions, persisted concatenated draft
text and did not carry ordered people into the next turn. Pass the Projection
to planning and engine, persist final AnswerResult text and ordered snapshot,
and forward revision events. HTTP regression checks the second request receives
the first displayed order. Talent and generic assistant retain their existing
entrypoints. Reasoning remains internal; public history/done omit private
reasoning while retaining workflow trace. Existing reasoning-retention tests
still verify internal persistence.

## Phase 8–9 — measured multi-model routing

Keep every existing task override. Add FAST/DEEP/VISION/EMBEDDING workload policy
and include capability/config-source in trace. The benchmark has 145 scored task
probes plus 8 separate post-change judge probes; see AI_MODEL_BENCHMARK.md.
No provider settings or saved routes changed. A capability labels workload;
it is not proof a provider model implements vision/tools. No new routing-profile
UI or broad default switch is justified by these small probes.

## Phase 10 — request cost and repeated dossiers

Live no-result requests reread identical six-person dossiers after widening.
Reuse only within the request when information need, mandatory/preferred
criteria, requested attributes, person ID, passages/order and source ownership
are unchanged. Changed evidence is read again. New candidates are never dropped.
Trace separately reports judge_sent and judge_reused. Tests update the real
document/index between passes to prove stale evidence is not reused.

Request-local ContextVar telemetry includes provider/model/task/capability,
route reason, per-attempt latency and reported input/output tokens, including
parallel judge/dense workers. The assistant bridge includes upstream intent/plan.
Missing usage is null in public trace, with tokens_complete=false; historical
LLMCall integer columns retain their legacy representation. No billing claim
may be made by summing unknown attempts as free calls. Embeddings validate all
coordinates, reject non-finite/bool values and report failures. The streaming
router consumes budget_seconds and bounds provider timeout; it is still not an
absolute end-to-end cancellation deadline.

## Phase 11–12 — security, recovery and UI gate

Strict judge schema, finite numbers, citation membership/person ownership,
partial coverage, bad embeddings, prompt-injection fixture, action target/surface
guards, public-reasoning removal and interrupted-stream recovery have regressions.
No sending, merge, reject, ownership claim or other consequential action added.
Existing module permissions and deferred HM/RM scope remain unchanged.

UI redesign is held: current criteria editing, source links and workflow steps
remain. The added API trace and factual/unknown labels provide the contract for
later observability UI. Real corpus recall, broader semantic-answer acceptance,
privacy review and scanned-CV evaluation must precede a "brain is correct" claim.

## Rollout and rollback

No migrations or persistent corpus rewrites. Release the coupled engine/guard/
telemetry changes together after the recorded gates; monitor incomplete reads,
fallbacks, citations, cache hit rate and real token/latency distributions.
Keep the existing task routes during canary. Roll back the source commits as a
unit and change the answer-cache namespace if restoring old judgement semantics.
Do not mix cached old judgement objects with the new verification contract.
This work was committed locally only; deployment and push are not performed.

## Continuation — conditional counts and consistent population coverage

The previous count fast path skipped retrieval/judging for every count shape.
Search-query expansions were unioned as FTS hits, which cannot implement AND or
NOT. Conditional counts now use the existing evidence pipeline, with a separate
per-condition judge contract and deterministic count/scope prose. Count results
remain model inferences; full-population totals are exact only for the supported
unconditional SQL count. Missing, malformed, failed and unsupported evidence is
visible separately from accepted matches. Counts are independent of display limits.

Live probes caught three further problems: missing Python information interpreted
as lack of Python skill; an added schema field ignored by the model; and names of
resolved group members conjoined as hard conditions. Use one coherent count schema,
retry malformed rows, reject UNKNOWN despite an overall true verdict, require a
negative quote for explicit-absence claims, and remove only standalone resolved
names from membership conditions. No skill/company taxonomy is used to select people.
The polarity check is necessary but insufficient for semantic entailment; complex
negation and unrelated negative sentences remain review risks.

Applicant filters now align corpus CV/index/chunk counts with the denominator.
Field coverage includes applicants lacking TalentProfile, repeated JSON-list values
count once per profile, and experience bucket labels match inclusive/exclusive bounds.
Conditional counts bypass cross-request cache until plan/route/eligibility versioning
is strengthened. Per-request dossier reuse and existing model routes remain intact.
SSE deterministic answers still run requested subsequent steps on the displayed people.

See [recorded continuation evidence](benchmark/BRAIN_V2_COUNTS.md), including failed
intermediate probes, final repeated live measurements and current regressions.
Rollback this continuation as one source change; do not restore the FTS estimate as
an exact semantic population count. No schema migration, production data write or
deployment is part of this continuation.

## Continuation — cache validity across data, route and permission changes

The retrieval/judgement cache previously bound only user text, user ID, conversation
projection and search-index timestamps. Prompt/route changes, role/module changes,
Person eligibility/name changes and raw Document updates could therefore reuse a
six-hour-old judgement. The cache key now binds applicant Person/Document/index
state, plan/judge prompt versions, effective plan/judge/embedding routing, and the
normalized plan that retrieval/judgement actually executed, plus the current
user's role/module scope. Missing fingerprint input disables caching. Equivalent
plan list ordering/case/whitespace is normalized; changed constraints, extraction,
retrieval queries, pool-affecting limit or sorting cannot reuse an older judgement.

Execution fingerprints are memoized per worker and follow the router's existing
cross-worker configuration stamp. No credential or PII is placed in the payload;
the stored key remains an opaque digest. Applicant corpus timestamps/counts avoid
hashing raw CV contents on the request path. Direct bulk SQL that bypasses timestamps
remains an operational limitation. Production hit-rate/latency is not measured.

See [cache validity evidence](benchmark/BRAIN_V2_CACHE.md). The initial three failed
counterexamples and final focused suite are retained in ignored local logs. No cache
flush, migration, route change, push or deployment was performed.

## Continuation — bind citations to the person claim

The final-answer verifier previously accepted a global set of valid source owners.
That allowed two candidates' source numbers to be swapped in the prose while still
passing, and short names could match inside unrelated words. Name detection now uses
complete Unicode word boundaries and checks every occurrence. At least one local
claim block for each mentioned person must contain a source owned by that person;
failure enters the existing one-shot repair/fallback path.

`trace.citation_audit` and the live `answer_eval` `citations_owned` check expose the
same contract. They explicitly report semantic entailment as NOT MEASURED: source
existence and assignment do not prove that the quote supports the model's conclusion.
See [citation assignment evidence](benchmark/BRAIN_V2_GROUNDING.md). No schema
migration, production write, model-route change, push or deployment was performed.
