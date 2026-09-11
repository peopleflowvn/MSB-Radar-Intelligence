# Oracle production deployment

## Cutover policy

Intelligence is deployed beside the Radar product core before any traffic is
switched. Radar remains the owner of authentication, RBAC, Person identity,
documents and business data. Replacing the entire Radar product with this
service would remove those required capabilities and is not a valid cutover.

The deployment has two distinct stages:

1. **Shadow:** build the exact Git commit on the Oracle self-hosted runner,
   attach `msbradar-intelligence` to `msbradar_default`, verify container health,
   then exercise the Radar feed, scope and evidence contracts without changing
   user traffic.
2. **Cutover:** only after real-corpus retrieval, evidence, security and
   performance gates pass, configure Radar's AI adapter to call the new service
   behind a reversible `INTELLIGENCE_ENGINE=v2` flag. The old AI path remains
   disabled but recoverable for rollback; the Radar product core stays live.

The first workflow is intentionally manual and accepts only
`DEPLOY_SHADOW`. It records the exact SHA in
`/home/ubuntu/msbradar-intelligence/current-sha` and verifies that the running
image tag contains that SHA. It does not edit Caddy or expose a public port.

## Production prerequisites

The existing `/home/ubuntu/msbradar/.env` must add the V2 names documented in
`.env.example`. Secrets must be provisioned directly on Oracle or through an
approved secret store; they must not be copied to GitHub logs or committed.
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
