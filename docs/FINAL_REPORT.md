# MSB Radar Intelligence V2 - Current Evidence Report

Date: 2026-09-11

This is an evidence report, not a claim that P0 is production-ready. Work that
can be completed safely inside the new repository is implemented and tested.
The remaining gates require Radar-side APIs, authorized real data, human labels
or live GreenNode configuration.

## Delivered

- Clean-room legacy system map and explicit reuse classification.
- Framework-independent public contracts and strict JSON boundary codec.
- Capability-based GreenNode chat and embedding adapters with mocked contract
  tests; business code does not select concrete model names.
- Haystack 3 document-store adapter, deterministic document lifecycle,
  chunk-to-Person/document mapping, delete, replay and reassignment handling.
- Radar document-feed and evidence-resolver HTTP clients.
- Page-atomic sync coordinator with durable namespaced SQLite checkpoints for a
  single process and safe retry after failure.
- Structured, lexical token, Haystack BM25, cosine semantic and hybrid
  retrieval components with Person-level grouping and deterministic fusion.
- Fail-closed citation validation against current source identity, version,
  hash, deletion and authorized Person scope.
- Strictly validated 50-case coverage seed and explicit separation between
  coverage cases and human-labelled scored truth.
- End-to-end automated path from indexing through scope-first retrieval to
  current-source evidence resolution.
- Liveness/readiness endpoints and privacy-safe operational trace schema.

## Measured results

All repository tests pass under Python 3.14 with `ResourceWarning` promoted to
an error. Compilation and whitespace validation also pass.

The only comparable retrieval numbers currently available are from a hashed,
six-person synthetic legacy fixture with 21 measured cases:

| Implementation | Recall@10 | Precision@10 | MRR | No-result accuracy |
|---|---:|---:|---:|---:|
| V2 token overlap | 1.000000 | 0.672807 | 0.912281 | 0.500000 |
| V2 Haystack BM25 plus token-presence gate | 1.000000 | 0.672807 | 0.973684 | 0.500000 |

These numbers do not measure semantic quality, production acceptance, answer
correctness, unsupported-claim rate, real latency, tokens or live model error
rate. They must not be used as production claims. BM25 is only the preferred
candidate for the next real-corpus benchmark.

## V1 versus V2

| Dimension | Legacy V1 evidence | V2 evidence | Decision |
|---|---|---|---|
| Architecture | Product-coupled Answer Engine exists in Radar | Independent contracts, adapters and lifecycle modules | Keep V2 boundary; no legacy orchestration port |
| Retrieval | Synthetic legacy report recorded Recall@10 1.0 and Precision@10 0.608730 | Synthetic results above | Promising only; real same-snapshot comparison required |
| Evidence | Legacy behaviors informed contract | Scope/version/hash/person/deletion checks tested | Live Radar resolver still required |
| Answer correctness | NOT MEASURED on a shared real corpus | NOT MEASURED | Grounded answering remains gated |
| Follow-up | NOT MEASURED on a shared suite | Contract only | Do not implement state before grounded Q&A gate |
| Latency/tokens/failure rate | NOT COMPARABLE | Synthetic retrieval latency only | Require live telemetry |

## Remaining external gates

1. Radar must expose an authorized incremental document feed and a current
   document snapshot/evidence resolver with a finalized opaque scope-token
   format. The legacy repository remains unchanged until that integration is
   explicitly requested.
2. An immutable, authorized real corpus snapshot and human-reviewed relevant
   Person IDs are required for at least the 50 coverage queries.
3. V1 and V2 must run against the same corpus and permission scope, capturing
   Recall, Precision, MRR, evidence accuracy, answer quality, unsupported claims,
   latency, tokens and failures.
4. Live GreenNode FAST, DEEP, VISION and EMBEDDING settings/credentials are
   required for model reliability and routing benchmarks.
5. A shared production index and checkpoint store, deployment topology, threat
   model, load/failure drills, trace sink and alerts must be selected and tested.

## Gate decision

P0 is **not done**. Index identity and scope-first security behavior are covered
by automated tests, but real retrieval and live evidence gates are not met.
Accordingly, Grounded Q&A, conversation state and Agent implementation have not
been started. Building them now would violate the master plan's requirement to
fix and measure retrieval before answer or agent optimization.
