# Oracle production deployment

## Current deployment policy

The new repository deploys both Product Core and Intelligence. Product Core
remains the owner of authentication, RBAC, Person identity, documents and
business data; Intelligence owns the derived retrieval representation and
grounded-answer capability. The legacy repository no longer deploys Oracle.

The deployment has two distinct stages:

1. **Validate:** test Intelligence, Product Core bridge and frontend from one
   exact commit on the Oracle self-hosted runner.
2. **Deploy:** back up PostgreSQL, retain the release, build both services,
   preserve the existing `msbradar` volumes, and set `INTELLIGENCE_V2_PRIMARY=1`.
3. **Verify:** require exact SHA, container health, public Product Core health,
   private feed/evidence authorization and index reconciliation before release
   retirement is considered complete.

The workflow is intentionally manual and accepts only `DEPLOY_PRODUCTION`. It
records the exact SHA in
`/home/ubuntu/msb-radar-platform/current-sha`, verifies the running image tag,
and retains the prior release for an application-only rollback. Product Core
continues to serve through the existing Caddy route; no legacy checkout or
legacy deployment workflow participates in production.

## Production prerequisites

The deployment keeps runtime files under
`/home/ubuntu/msb-radar-platform/runtime/` with an explicit allow-list. It
preserves the existing Product Core database and R2 configuration without
committing or printing either. Integration tokens are generated on Oracle,
retained across deploys and never printed. The embedding model must use its
reviewed production route; missing or failed provider capacity is reported as
an operational state, not silently replaced by a chat model.
Secrets must not be copied to GitHub logs or committed.
The Radar service token must authorize only the document feed and evidence
resolver contracts, never general admin access.

## Rollback

Retain the last healthy release. Rollback means switching the `current`
release symlink, recreating Product Core and Intelligence from that release,
and verifying public health. It must not restore PostgreSQL during a normal
application rollback: database restore is a separate approved data-recovery
operation. Release cleanup happens only after the observation window.

## Required production evidence

- workflow conclusion is `success` and `headSha` equals the intended commit;
- `current-sha`, running image tag and GitHub `headSha` agree;
- container health and `/health` pass;
- `/ready` passes without printing secret values;
- unauthorized Person never enters retrieval or model context;
- feed replay, delete, stale-document and evidence-resolution probes pass;
- the non-PII reconciliation reports `eligible_minus_indexed: 0` before the
  derived index is considered caught up;
- a scoped search returns only authorized evidence; if embedding capacity is
  unavailable, the documented Haystack BM25 degradation path remains bounded
  and observable.
