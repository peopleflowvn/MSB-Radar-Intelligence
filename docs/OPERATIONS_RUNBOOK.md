# Production operations runbook

## Ownership

`MSB-Radar-Intelligence` is the only production release repository. Product
Core is tracked at `product_core/`; its PostgreSQL data volume and R2 objects
remain the source of truth. The Intelligence index is a disposable derived
representation stored in `intelligence_state`.

## Pre-deploy gate

1. Run the full Intelligence test suite and Product Core bridge tests.
2. Build the unchanged frontend and run its tests/typecheck.
3. Run the synthetic Haystack BM25 evaluation. It is a regression gate only,
   not evidence of real-corpus quality.
4. Require a production database backup created by the deployment workflow.

## Post-deploy gate

1. Confirm Actions `headSha`, `/home/ubuntu/msb-radar-platform/current-sha`,
   and the Intelligence image tag all match.
2. Run `Probe Oracle Intelligence`. It validates non-secret readiness, the
   private feed/evidence contracts, token rejection, index counts and a scoped
   search.
3. Read `eligible_minus_indexed` from the probe. It must reach zero before
   treating the index as fully caught up.
4. Verify login, OTP, Talent access and a grounded answer with an authorized
   non-administrator account. Do not log candidate names, CV text or tokens.

## GreenNode rate limiting

The indexer uses one-document pages, one embedding input at a time and a
five-second minimum interval. HTTP 429 is reported as provider capacity, not
as an authorization or data-loss event. It retains its cursor and retries on a
later loop. Do not restart repeatedly or increase concurrency while 429s are
present.

## Rebuild and restore

The PostgreSQL/R2 source data must never be rebuilt from the Intelligence
index. If the derived index is damaged, stop the indexer, back up its SQLite
file, remove only the derived `index.sqlite3` and cursor, then restart the
indexer. It will replay the authorized Product Core feed. Record the resulting
count reconciliation in the deployment evidence.

## Rollback

The deployment workflow retains each release and creates a compressed PostgreSQL
backup before migration. Application rollback means changing the `current`
symlink to the last verified release and recreating Product Core and
Intelligence from that release. Restore PostgreSQL only after a separately
approved data-recovery decision; it is not a normal code rollback operation.

## Secrets

Runtime files stay under `/home/ubuntu/msb-radar-platform/runtime/` with mode
`600`. Never print or commit them. Rotate the two Intelligence bridge tokens if
a runner, log, or production host is suspected to be exposed.
