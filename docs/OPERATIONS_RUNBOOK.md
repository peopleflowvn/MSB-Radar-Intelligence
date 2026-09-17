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

## AI observability

Langfuse is opt-in. Configure all of `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` to enable it; otherwise requests
run normally without remote telemetry. Use a controlled self-hosted endpoint.
The integration sends only operation names, execution class and aggregate
counts. It must not receive questions, prompts, CV/evidence content, person
identifiers, scope tokens or model reasoning. Telemetry errors must never fail
an answer request.

## Rebuild and restore

The PostgreSQL/R2 source data must never be rebuilt from the Intelligence
index. If the derived index is damaged, stop the indexer, back up its SQLite
file, remove only the derived `index.sqlite3` and cursor, then restart the
indexer. It will replay the authorized Product Core feed. Record the resulting
count reconciliation in the deployment evidence.

## Growth evidence index (semantic prospect search)

`rb_prospectevidencechunk` is a derived, rebuildable index of customer evidence
(social posts, RB signals, product interests, outreach outcomes, RB profile),
already contact-redacted. It never replaces the source tables.

After the migration that creates it, run once, in order:

```bash
docker exec msbradar-hub python manage.py rebuild_prospect_evidence_index
docker exec msbradar-hub python manage.py embed_prospect_evidence --limit 0 --then-pin
```

Until the first rebuild completes without errors, Growth retrieval keeps using
its previous `icontains` branches; only a complete run sets the backfill marker
that switches social/signal matching to the indexed full-text path. A partial
index must never replace the old path, or unindexed customers become invisible.

After that, saves keep the text index current (`RB_EVIDENCE_INDEX_ON_SAVE`,
default on). Vectors are filled by `embed_prospect_evidence` — run it on the same
schedule as `embed_talent_index`. Both use the `talent_embedding` route: query and
document vectors must come from the same model, and `pin_vector_dimensions` pins
both indexes together. After changing the embedding model, re-embed both.

Check state with the `semantic_retrieval` field in an answer trace's coverage:
`INDEX_EMPTY`, `INDEX_NOT_EMBEDDED`, or `ENABLED`. For a bulk import, set
`RB_EVIDENCE_INDEX_ON_SAVE=0`, import, then rerun the rebuild.

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
