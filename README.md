# MSB Radar Intelligence

Clean-room intelligence service for MSB Radar. The legacy product remains the
source of truth for people, identity, permissions, workflows, and documents.
This repository owns retrieval representations, evidence-backed answering,
model routing, evaluation, and (only when justified) agent tools.

## Current milestone

Phase 0/1 foundation:

- legacy system map and reuse decision log;
- framework-independent public contracts;
- deterministic evidence validation;
- GreenNode capability gateway with injectable transport;
- in-memory person-grouped hybrid retrieval reference implementation;
- 50-case legacy-derived gold-set seed;
- runnable health endpoint and tests without external credentials.

Haystack and a production store are deliberately not installed yet. They enter
after the contracts, gold-set schema, and retrieval baseline are stable.

## Run locally

Requires Python 3.9+.

```powershell
python -m unittest discover -s tests -v
python -m radar_intelligence.api
```

Then open `http://127.0.0.1:8081/health`.

## Design rules

- Radar authorizes scope before calling this service.
- Every request carries a non-empty opaque `scope_token`.
- Person identity is never merged here.
- Search returns people, not ungrouped chunks.
- Factual answer claims reference validated evidence IDs.
- Business code selects capabilities; configuration selects model names.
- No consequential action executes without explicit human approval.
