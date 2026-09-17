# Brain V2 completion status — 2026-09-08

This is a local implementation ledger, not a production acceptance certificate.

Final validation: `ai.tests_streaming`, `talent.tests_answer`, and
`ai.tests_review_eval` passed 177 tests in 65.226 seconds using in-memory SQLite.
The HTTP probe's four loopback tests passed in 0.575 seconds. `git diff --check`
passed. These runs use fixtures/model mocks and do not establish deployed quality.

## Implemented in the continuation

- Five-turn HTTP/SSE persistence regression, replacement result and isolated
  conversations; fixed routing for positional follow-ups without question marks.
- Bounded HTTP load command with protocol errors, first-answer latency, P50/P95
  and throughput. It has loopback fixture tests; no deployed measurement yet.
- Human review schema v2 retains repeated sentence/source pairs and missing source
  references. Legacy batches remain readable with explicit legacy coverage.
- Talent runners reject incomplete/error streams, mark aborted persistence, and
  emit successful completion only after persistence succeeds.
- Assistant stream errors and incomplete output no longer end with successful done.

## Open work and the evidence required to close it

| Item | Current limit | Required next evidence/work |
|---|---|---|
| Recruiter correctness and entailment | Worksheets exist; no independently supplied truth labels | Two reviewers label real representative cases; adjudicate disagreements |
| PostgreSQL/vector recall | Fictional SQLite probes cannot measure real vector retrieval | Authorized representative database/index snapshot, relevance labels, reproducible comparison |
| Scanned CV and embedding quality | No representative scan comparison recorded | Authorized scan/text pairs and verified extraction truth; OCR and embedding benchmark |
| Deployed five-turn UI and load | Local HTTP contract tests and load tooling exist | Authenticated test account/corpus on the deployed endpoint; record model, route, revision and tail latency |
| Provider cancellation | Client deadlines do not kill blocked provider I/O | Cancellation-aware provider transport or isolated worker lifecycle, fault/load tests and rollout validation |
| Exact structured counts | Evidence-bounded conditional counts preserve unknown coverage | Validated predicate schema, current complete facts/provenance, population audit before enabling exact claims |
| Routing profiles and cost policy | Existing per-task routes retained | Representative quality/latency/cost comparison before route or profile redesign |
| Cross-process resume and admission | Process-local admission now caps real active workers; registry remains process-local | Shared durable job state and deployment-wide admission; deployment architecture and load validation |

The open rows include implementation work as well as external acceptance evidence.
They must not be marked complete from passing unit tests. No deployment or business
model-route change was performed by this continuation. Uncited factual assertions
still need whole-answer human review; sentence/source export is not exhaustive
semantic claim extraction.

## Deployment and admission continuation — 2026-09-09

Commit `31065a3` deployed successfully in GitHub Actions run `34225897066`.
Public `/api/v1/health/` returned HTTP 200 with `ok=true` after deployment.
CI ran all 1,584 Hub tests successfully on Python 3.9 and 3.11, then failed Ruff
on two unused symbols in earlier count/superlative changes; those are removed in
this continuation. UI, agent and secret checks passed; Windows Edge was skipped.

Talent's threaded runner now admits at most `ANSWER_RUNNER_MAX_WORKERS` workers
per process (default 8, configurable through Compose). It rejects duplicate active
turn IDs and overload before starting another provider call. Slots stay occupied
after client timeout until the worker actually exits, and are released on thread
start failure or cleanup. Rejections emit SSE errors and do not persist an empty
answer or overwrite another active turn's status. SQLite inline and Assistant's
separate execution path are outside this cap. This is not hard cancellation,
cross-process deduplication, or a measured production concurrency SLA.

## Shared resume continuation

`a85076e` subsequently deployed successfully (run `34255225219`), with successful
CI (`34255225160`) and HTTP 200 health after deployment.

The next local increment publishes running/error/timeout/done metadata through the
existing database cache, scoped by user and a hash of the client turn ID. A process
without the local registry can read this status. Running metadata carries an epoch
deadline so a lost worker cannot report running forever. Cache failure falls back
to the local registry, and cache eviction/expiry can still yield unknown. No answer
text, question or credentials are placed in these cache records. This is temporary
shared status, not durable job execution, cluster-wide deduplication or global slots.

Persisted assistant messages now carry the client turn ID in metadata. Resume uses
that exact ID; old messages can only use the immediately adjacent legacy answer.
It no longer skips an intervening turn and returns another turn's answer from
the same conversation. User/CV permissions continue to apply.

Validation includes absent-local-registry reads, user isolation, abandoned-worker
deadlines, independent database cache instances, cache failure, overlapping turns,
and legacy resume. Tests do not constitute a real multi-process deployment run.

## Durable duplicate prevention continuation

The next increment adds `ai.AnswerRun` and migration `0018_answer_run_claim`.
A unique `(user, client_turn_id)` claim is created before starting the Talent
background thread. Processes sharing the database cannot both create that claim.
A duplicate or unavailable database fails closed before model execution and does
not persist an empty answer. Finished and expired IDs are not reclaimed: a blocked
provider may still be alive after the response deadline. Retrying generation uses
a new turn ID; the old one remains available for resume/status inspection.

The table contains user ownership, turn ID, state and timestamps only. Terminal
updates are conditional on running state; cache loss falls back to durable status.
Worker death is observed as timeout from its deadline without requiring a heartbeat.
Claims are kept as idempotency records and cascade with account deletion; no automatic
pruning/reclaim is enabled because deletion would permit replay of an old turn ID.
This requires running migrations before enabling the new server code.

Scope remains Talent's threaded runner. Inline SQLite, Assistant's separate path,
global admission across processes and hard provider cancellation remain outside
this change. The unique constraint is tested locally; a simultaneous multi-process
PostgreSQL fault/load run has not yet been recorded. At this local validation stage,
production deployment was still pending; the result is recorded immediately below.

## Final deployment verification — 2026-09-09

Commit `f425cdb` deployed successfully in workflow `34303643888`; the workflow's
migration/container health step passed for that exact SHA, and the public health
endpoint returned HTTP 200. CI `34303643821` passed Hub on Python 3.9 and 3.11,
web test/typecheck/lint/build, Agent test/lint/container build and secret scan. The
first web attempt timed out in an unchanged Person360 test at 5 seconds while the
runner was loaded; the isolated failed-job rerun passed all web stages.

Production preflight `34304917969` confirmed PostgreSQL with 1,075 people and 679
documents. Enabled GreenNode and Gemini provider configurations resolved without
printing keys. Gemini embedding-001, embedding-2-preview and embedding-2 each
returned a 1,536-dimensional vector. Preflight establishes configuration/readiness,
not retrieval relevance or OCR quality.

## Phase and Definition-of-Done verdict

| Phase | Engineering status | Acceptance boundary |
|---|---|---|
| 0 Baseline/audit | Complete | Current architecture, call map, hotspots and ten root causes recorded |
| 1 Gold/eval harness | Complete for synthetic contracts | Independent production truth set remains external work |
| 2 Failure taxonomy | Complete for observed runs | Production incidence rates require representative traffic |
| 3 Intent/retrieval fixes | Implemented and regression-tested | Production Recall@K awaits labelled clone pilot |
| 4 Intelligence snapshot | Incremental projection v2 implemented/audited | Extraction coverage and semantic truth are incomplete |
| 5 Judge/evidence | Implemented with schema, provenance and human-review workflow | Two real independent reviewers have not labelled a batch |
| 6 Aggregate/compose | Implemented for deterministic count/sort and verified citations | Conditional semantic whole-store counts remain bounded inference |
| 7 Conversation/follow-up | Implemented through five-turn HTTP contract, durable resume and dedupe | Deployed authenticated five-turn model/UI acceptance is unmeasured |
| 8 Multi-model benchmark | Complete for recorded synthetic workloads | Vision/cost and representative production comparison remain incomplete |
| 9 Routing V2 | Capability/task routing implemented; current routes preserved | Profile redesign waits for quality/cost evidence |
| 10 Token/latency/cache | Implemented and synthetically measured | Production cache hit, cost/query and concurrent P95 are unmeasured |
| 11 Security/recovery | Regression/adversarial gates, failure states, deadlines, admission and durable claims implemented | Python cannot hard-kill a blocked provider call; cluster-wide slot cap remains open |
| 12 UI/observability | Criteria/evidence/workflow trace and Settings latency/failure metrics implemented | Full live UI acceptance and broader profile UX remain open |

All Definition-of-Done artifacts requested by the plan exist: baseline, architecture
and AI-call maps, failure taxonomy, versioned gold/eval harness, local retrieval and
evidence metrics, follow-up tests, token/latency comparisons, GreenNode multi-model
benchmark, routing recommendation, regression/adversarial evidence, before/after,
remaining weaknesses and updated final report. Therefore the **engineering plan is
complete within the authorized code and synthetic/operational evidence scope**.

The **product acceptance plan is not complete**. It still requires independent
recruiter labels, a specifically authorized clone/index pilot on production-derived
profiles, scanned-CV truth pairs, authenticated deployed five-turn/load measurement,
and a cancellation-aware provider transport or isolated worker process. These inputs
cannot be truthfully manufactured from unit tests. The benchmark-clone workflow is
ready but was not run because it copies and processes 50 production profiles and
requires explicit authorization for that data operation.
