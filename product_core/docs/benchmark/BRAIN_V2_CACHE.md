# Brain V2 — cache validity continuation

Date: 2026-09-08. Scope: local code and synthetic/test identities. Production
cache hit rate and latency are NOT MEASURED.

The Answer Engine caches retrieval and judgement for six hours. Its prior key
included normalized user text, user ID, conversation projection and indexed
corpus timestamps. Three focused counterexamples failed before this change:

- planner/judge prompt or effective model-route changes reused an old entry;
- changing the same user's role or module grant reused an old entry;
- changing Person eligibility/name or raw CV text before reindexing reused an
  old entry.

The key now adds four independently hashed inputs:

1. Corpus: applicant Person count/latest update, applicant Document count/latest
   update, and applicant search-document/chunk count/latest update. This includes
   identity/eligibility and raw-text changes before the asynchronous index catches up.
2. Execution: planner and judge prompt hashes plus effective plan, judge and
   embedding route/provider/model/order. Safe fallback provider configuration is
   included; credentials and key hints are never read into the key payload.
3. Plan: normalized shape, information need, mandatory/preferred conditions,
   requested extraction, retrieval queries and sort. Reordered/case/whitespace
   equivalents share a key; a different condition or retrieval direction does not.
   Requested limit is included because it changes retrieval-pool size. Subsequent
   actions remain downstream of the cached stages.
4. Permission: authentication/activity/superuser state and the user's current
   role/module set. The key remains per user.

Failure to compute any required fingerprint disables the cache for that request.
It does not fall back to a partially scoped key. The opaque key exposes only
SHA-256 digests.

The execution fingerprint is reused inside each worker. The router's existing
configuration stamp refreshes other workers within its configured polling TTL;
the worker that handles a Settings write receives a new router immediately.
Prompt and safe routing-environment hashes are part of the in-process marker.

## Verification

- Before: 9 focused tests, 3 failures matching the counterexamples above.
- After: 12 focused cache tests pass in 1.033 seconds, including a real pipeline
  miss followed by a hit with the same executed plan.
- A local persistent-DB query-count probe observed 26 queries for the first key
  in a fresh process and 4 for the immediately repeated key. The first cost is
  process/config-change initialization; the four repeated queries refresh corpus
  state. Authenticated requests additionally read roles and module overrides.
- Final affected backend regression: 799 AI/Talent/Intel/People tests pass in
  134.368 seconds. Missing or failed logs must remain NOT MEASURED.

This does not measure production cache hit rate or prove row-level authorization.
Current Talent authorization remains module-level. If row-level scoping is added,
its explicit scope/version must enter the permission fingerprint before rollout.
The corpus uses timestamps and counts rather than hashing all CV text; direct bulk
SQL that bypasses auto-managed timestamps and indexing can still evade invalidation
and must be forbidden or followed by a rebuild/version bump.

Rollback the cache/runtime and tests together. Old stored entries become
unreachable because the derived key changes; no destructive cache flush or schema
migration is required.
