# Public API Contract

This contract is framework-independent. Public callers never send or receive
Haystack documents, pipeline objects, concrete model names, or provider SDK
types. JSON field names use `snake_case`; unknown fields are rejected once the
HTTP adapter is introduced.

## Request envelope

Every search or answer request contains a non-empty `principal_id` and opaque
`scope_token`. The token represents a scope authorized by Radar. Intelligence
must fail closed when either value is absent and must never broaden the scope.
The eventual HTTP adapter will also require a caller-generated `request_id` for
idempotency and tracing.

## Search

`SearchRequest` contains `query`, authorized scope, optional structured
`filters`, optional `thread_id`, and a bounded `limit` from 1 to 100.
`SearchHit` is grouped by `PersonRef`, not by chunk, and carries a normalized
score plus zero or more validated `Evidence` objects.

Supported filter fields are locations, all-required skills, companies,
education, minimum/maximum experience, and excluded terms. Adding a filter is
a versioned contract change; free-form provider metadata is not accepted.

## Answer

`AnswerRequest` contains a question, authorized scope, optional bounded thread
reference and optional Person IDs. `AnswerResponse` contains answer text,
people, evidence, cited evidence IDs, interpreted query, and model traces.
Every cited ID must exist in the returned evidence package and pass current
scope, document version, deletion, and Person ownership checks.

## Stable references

- `PersonRef`: Radar-owned Person ID and optional display label.
- `DocumentRef`: Radar-owned document ID, Person ID, version, content hash and
  optional source-record ID.
- `Evidence`: immutable evidence ID, Radar references, source, exact passage,
  source location, score, content hash and document version.

Intelligence cannot create, merge, split or redirect a Person. Display labels
are not identity keys.

## Conversation and actions

`ThreadState` is partitioned by principal and scope fingerprint and stores only
bounded stable references. `AgentAction` defaults to `proposed`. A
consequential action cannot become approved or executed without `approved_by`;
Radar revalidates permission and business policy at execution time.

## Errors

The future transport maps validation failures to `INVALID_ARGUMENT`, missing
or invalid scope to `PERMISSION_DENIED`, stale/deleted sources to
`STALE_EVIDENCE`, provider timeouts to `MODEL_TIMEOUT`, and unavailable
dependencies to `DEPENDENCY_UNAVAILABLE`. Errors expose a request ID but never
secrets, raw scope tokens, or unnecessary PII.
