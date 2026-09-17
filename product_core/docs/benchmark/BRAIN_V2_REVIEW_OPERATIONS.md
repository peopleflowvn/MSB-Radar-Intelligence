# Brain V2 — review, provenance and operations continuation

Scope: local implementation and tests. Production acceptance remains unmeasured.

Validation: broad AI/Talent/Intel/People regression passed 812 tests in 197.389 s.
After final review-integrity, error classification, source-state and runner refinements,
31 affected tests passed in 7.575 s. Frontend TypeScript/Vite production build passed;
Vite still warns about the existing large JavaScript bundle. No live UI acceptance
or production load measurement was performed.

## Independent review

`brain_review_export --input <report.json> --out <ignored-directory>` creates
answer, returned-candidate and cited-claim worksheets with two reviewer slots.
`brain_review_score --file <reviews.jsonl> --manifest <manifest.json> --out
<score.json> --require-complete` rejects an empty, incomplete, disputed or altered
batch. Changes to review content invalidate its hash; only reviews and adjudication
can change. Disagreements require a third reviewer ID. IDs are declarations, not
authentication or proof of independent work.

Reports measure acceptance among returned candidates, answer acceptance, and
contradicted/unsupported rates among finalized cited-claim records. Missing labels
produce null metrics. Schema v2 exports every sentence/source pair, including reuse
of a source in later sentences. References to nonexistent sources are retained with
`source_missing=true` and null evidence, rather than silently dropped. Each pair has
answer offsets and a distinct review ID. Missing evidence is flagged mechanically;
human labels are still required. Grouped citations create one pair per distinct
source in that sentence, so these metrics measure evidence pairs, not unique facts.
Schema v1 batches remain scoreable and are explicitly marked as legacy coverage.
Sentence segmentation is mechanical; uncited statements are only covered by the
whole-answer review, not exhaustive claim-level labels. Corpus recall needs a
separate independently labelled population.
Keep production worksheets under ignored `docs/benchmark/label_batch/` or outside
the repository. No recruiter labels were fabricated.

## Materialized provenance

Projection version 2 preserves fact ID, status, extractor/model/schema, validity,
source document/record IDs and versions, and a fact/source state digest. The existing
rebuild command includes empty applicant projections so missing facts and missing
builds are distinguishable. `audit_search_projection --gate` checks identity,
versions, state, extraction coverage and field coverage. It is read-only and does
not switch search readers to the projection.

Local inventory previously observed 8 applicants and only 1 completed extraction
(12.5%). Rebuilding eight projections cannot establish extraction completeness.
An accepted fact, or a completed extraction, also does not certify semantic truth.
These gates must not be used as proof that semantic whole-population counts are exact.

## Runtime and Settings

The threaded Talent runner bounds client response waiting, reports timeout/error,
marks incomplete persistence aborted, and avoids blocking forever on a full terminal
queue. Resume reports timeout as HTTP 504. This is a response deadline: Python cannot
forcibly terminate a provider thread blocked in I/O. Inline SQLite and Assistant's
separate stream path do not gain hard cancellation from this change.

The final runtime pass also rejects engine EOF without a final result and explicit
engine errors. Inline and threaded Talent runners persist an aborted result for
incomplete generation. They release the successful terminal event only after
persistence succeeds; persistence failure becomes an error. The threaded consumer
also reads the terminal outcome after draining a queue whose sentinel could not fit.
Assistant corpus/conversation/tool streams track completion and failure separately:
an error or missing final result is saved as aborted and does not emit a successful
done event. This does not implement provider cancellation or cross-process resume.

Settings usage now defaults to the latest 24 hours (API `hours` range 1–720), with
successful-call P50/P95 and mutually exclusive timeout/rate-limit/authentication/other
error categories. Classification uses recorded error text; provider-specific wording
can remain in "other". These are per-call metrics, not end-to-end request latency.
Historical token zeros and non-primary-provider counts retain their existing limits.

## Remaining acceptance work

Representative PostgreSQL/vector retrieval, independent recruiter review, real
scanned CV/embedding comparisons, live five-turn HTTP/SSE, concurrent-load testing,
provider cancellation, exact validated structured counts and routing profiles remain
open. No production acceptance, deployment or model-route change is implied by tests.
