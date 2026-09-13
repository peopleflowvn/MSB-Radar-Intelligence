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

The first workflow is intentionally manual and accepts only
`DEPLOY_SHADOW`. It records the exact SHA in
`/home/ubuntu/msbradar-intelligence/current-sha` and verifies that the running
image tag contains that SHA. It does not edit Caddy or expose a public port.

## Production prerequisites

The deployment creates `/home/ubuntu/msbradar-intelligence/runtime.env` with an
explicit allow-list. It may read the existing GreenNode base URL, API key and
general model from `/home/ubuntu/msbradar/.env`, but never copies database,
R2, Django or unrelated provider secrets. Integration tokens are generated on
Oracle, retained across deploys and never printed. The embedding model remains
blank until its production route is explicitly inspected and tested.
Secrets must not be copied to GitHub logs or committed.
The Radar service token must authorize only the document feed and evidence
resolver contracts, never general admin access.

## Rollback

Before cutover, retain the last healthy image tag and adapter flag value.
Rollback means restoring `INTELLIGENCE_ENGINE=v1` and verifying Radar health;
it must not restore a database backup because the shadow service does not own
Radar business data. Image cleanup happens only after the observation window.

## Required production evidence

- workflow conclusion is `success` and `headSha` equals the intended commit;
- `current-sha`, running image tag and GitHub `headSha` agree;
- container health and `/health` pass;
- `/ready` passes without printing secret values;
- unauthorized Person never enters retrieval or model context;
- feed replay, delete, stale-document and evidence-resolution probes pass;
- V1/V2 benchmark uses the same authorized corpus snapshot;
- rollback flag has been exercised before public traffic is switched.
