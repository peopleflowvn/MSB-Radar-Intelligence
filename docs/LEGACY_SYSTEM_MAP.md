# Legacy MSB Radar System Map

## Discovery record

- Legacy checkout: `D:\\Project\\MSB_Radar`
- Observed branch: `develop` tracking `origin/develop`
- Observed remote: `https://github.com/peopleflowvn/MSB-Radar.git`
- Discovery mode: read-only. No legacy files, data, dependencies, or Git state
  were changed.
- Evidence reviewed: root README, `docs/`, server models, Talent Answer Engine,
  provider/router code, tests, Edge documentation and configuration inventory.

This map records boundaries and contracts. It is not an endorsement of every
legacy implementation detail.

## Product topology

| Area | Legacy location | Responsibility | V2 boundary |
|---|---|---|---|
| Product UI | `web/` | React workspaces and user interaction | Keep external |
| Product API | `server/` | Django business API and authorization | Keep external |
| People core | `server/people/` | Person, identities, relations, interactions, opportunities | Keep external |
| Source/document core | `server/core/` | SourceRecord, Document, parsed text, ingest and projection | Keep external; consume contracts |
| Talent | `server/talent/` | Talent profile, search, hunts and recruitment behavior | Keep workflow; reimplement intelligence contracts |
| Growth/RB | `server/rb/` | signals, suggestions, claims and opportunities | Keep workflow external |
| Accounts/access | `server/accounts/` | authentication, roles, feature access, quotas, AccessLog | Keep external and authoritative |
| AI platform | `server/ai/` | provider configuration, routing, graph/runtime, tools and conversation | Adapt transport concepts only; do not port orchestration |
| Answer Engine | `server/talent/answer/` | PLAN/RETRIEVE/JUDGE/AGGREGATE/COMPOSE | Do not port |
| Edge | `edge/` | collection, local credentials, parsing, checkpoints and outbox | Keep external |
| Agent service | `agent/` | legacy AgentBase prospect integration | Reference only; agent deferred |

## Authoritative entities and rules

### People and identity

`Person` means one human across sources and time. `Identity` resolution is
deterministic and biased against false merges. Intelligence may accept a
`person_id` and may group search representations by it, but cannot create,
merge, split, or redirect people.

### Documents and provenance

`SourceRecord` represents an application/source event. `Document` represents a
file, while parsed text has its own version/provenance lifecycle. Intelligence
indexes a versioned search representation containing stable Radar references;
it does not become a second CV or business database.

### Permissions

Django authentication, role/module access, contact quotas, CV download rules,
and `AccessLog` remain in Radar. V2 requires a pre-authorized opaque scope on
every search/answer request and must propagate it to every Radar data call.
Cache and state keys must include the calling principal and scope.

### Workflows

Talent hunts, recruitment pipelines, RB suggestions/opportunities, claim locks,
SLA transitions, and DNC are product-owned. V2 may propose or explain an action;
Radar validates and executes it after human approval.

### Edge and synchronization

Edge owns recruitment-site sessions, downloads, parsing initiation, retries,
checkpoints, and outbox delivery. Hub owns ingest and business projection. V2
receives change events or pulls an authorized document feed; it does not touch
local Edge state.

### Search and answering

Legacy deterministic search covers structured fields, Boolean behavior,
Vietnamese normalization, exact matching, aggregates, and permission-aware
views. The current legacy answer path is under `server/talent/answer/`; older
graph and agent modules also exist under `server/ai/`. V2 preserves verified
behavior through tests and contracts, not by copying the orchestration.

### GreenNode

GreenNode is the primary inference platform. Useful legacy concepts are an
OpenAI-compatible transport, provider configuration, timeouts, error mapping,
usage accounting, and task/model routing. V2 routes `FAST`, `DEEP`, `VISION`,
and `EMBEDDING` capabilities to configured models without leaking model names
through public API contracts.

## Integration seams to specify

1. Authorized search/read API from Radar to Intelligence.
2. Incremental document upsert/delete/reassignment feed with content hashes.
3. Batch Person merge notification that only rewrites index references.
4. Evidence resolver from stable references to an authorized Radar location.
5. Trace/audit event handoff without raw secrets or unnecessary PII.
6. Human-approved action proposal contract; no direct product mutation in P0.

## Known unknowns

- Production document-feed and scope-token formats are not yet fixed.
- A live GreenNode call was not made; credentials/configuration are not copied.
- A safe legacy baseline run still needs a dataset and runtime decision.
- Index/store choice and Haystack components require benchmark evidence.
- Exact retention and deletion SLA between Radar and the index needs governance.

