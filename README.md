# MSB Radar Intelligence

Clean-room intelligence service for MSB Radar. The legacy product remains the
source of truth for people, identity, permissions, workflows, and documents.
This repository owns retrieval representations, evidence-backed answering,
model routing, evaluation, and (only when justified) agent tools.

## Current milestone

Production foundation:

- legacy system map and reuse decision log;
- framework-independent public contracts;
- deterministic evidence validation;
- GreenNode capability gateway with injectable transport;
- OpenAI-compatible GreenNode chat transport with sanitized errors and usage
  accounting (mock-contract verified; live credentials not configured);
- in-memory person-grouped hybrid retrieval reference implementation;
- 50-case validated legacy-derived gold-set seed;
- incremental document conversion/index lifecycle with idempotent events,
  delete tombstones, Person reassignment and injectable embeddings;
- Haystack 3.1 indexing adapter verified against its real in-memory store;
- authorized structured/lexical/semantic-adapter hybrid retrieval and explicit
  Recall@K, Precision@K and MRR evaluation primitives;
- benchmarked Haystack BM25 candidate with nonmatch gating and improved
  synthetic MRR over token overlap;
- LangGraph orchestration for scope authorization, retrieval, grounded
  generation, evidence validation and explicit no-evidence completion;
- opt-in Langfuse tracing with metadata allow-listing;
- optional offline Ragas evaluation and Docling document conversion adapters;
- runnable health endpoint and tests without external credentials.

Haystack 3.1.1 is installed in the project-local environment and exercised by
integration tests. A durable production store is deliberately not selected
until the Radar feed, deletion SLA and real-corpus benchmarks are agreed.

Current phase and gate evidence is tracked in `docs/PHASE_STATUS.md`. Grounded
answering is active behind the public contract. Product Core still owns
authentication, authorization, business workflows and conversational UX; the
graph cannot execute consequential business actions.

## Run locally

Requires Python 3.10+. Development uses the project-local Python 3.14 virtual
environment.

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python -m radar_intelligence.api
```

Then open `http://127.0.0.1:8081/health` for liveness. The `/ready`
endpoint returns HTTP 503 plus missing configuration names until Radar and
GreenNode live dependencies are configured; it never returns secret values.

## Design rules

- Radar authorizes scope before calling this service.
- Every request carries a non-empty opaque `scope_token`.
- Person identity is never merged here.
- Search returns people, not ungrouped chunks.
- Factual answer claims reference validated evidence IDs.
- Business code selects capabilities; configuration selects model names.
- No consequential action executes without explicit human approval.
