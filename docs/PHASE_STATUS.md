# Delivery Phase Status

Status is evidence-based: `DONE` means the stated deliverable exists and its
current automated checks pass; `PARTIAL` identifies the missing live or
production evidence explicitly.

| Phase | Status | Evidence | Remaining gate |
|---|---|---|---|
| 0 Legacy discovery | DONE | `LEGACY_SYSTEM_MAP.md`; legacy checkout read-only | Refresh map when legacy contracts change |
| 1 Reuse classification | DONE | `LEGACY_REUSE_MANIFEST.md`; every used legacy fixture is recorded | Record every future reused primitive |
| 2 Architecture/contracts | DONE | Framework-independent dataclasses, architecture and API contract | Version HTTP serialization when adapter exists |
| 3 Gold Set/baseline | PARTIAL | 51 query coverage cases; 21 retrieval cases measured on hashed six-person synthetic fixture | Human-labelled real corpus and V1 run on identical authorized snapshot |
| 4 GreenNode gateway | PARTIAL | Capability routes, chat/embedding transport and mock contract tests | Live configured FAST/DEEP/VISION/EMBEDDING calls and telemetry |
| 5 Indexing | PARTIAL | Converter, metadata, embeddings, replay/delete/reassignment; Haystack 3.1.1 integration tests | Durable production store, Radar feed and reindex/delete SLA |
| 6 Retrieval | PARTIAL | Structured, token lexical, Haystack BM25, cosine semantic adapter, hybrid fusion and scope-before-retrieval tests | Live embedding benchmark on real labelled corpus |
| 7 Person reranking | PARTIAL | Person grouping, best-evidence selection, RRF and synthetic MRR measurement | Real-corpus reranking comparison and selected thresholds |
| 8 Evidence | PARTIAL | First-class evidence contract and deterministic citation/deletion/Person checks | Authorized live source resolver and stale-version verification |
| 9 Grounded RAG | BLOCKED BY GATE | Not implemented | Phases 3, 6, 7 and 8 live gates |
| 10 Conversation state | NOT STARTED | Contract only | Grounded Q&A gate |
| 11 Agent | NOT STARTED | Action contract only | Demonstrated multi-step need and RAG comparison |
| 12 Model benchmark | NOT STARTED | Capability abstraction only | Live GreenNode configuration |
| 13 Legacy vs V2 | PARTIAL | Comparable synthetic lexical report | Same real corpus, scope and telemetry |
| 14 Radar integration | PARTIAL | Integration contract draft | Agreed product endpoints and scope-token format |
| 15 Hardening | NOT STARTED | Foundational fail-closed tests only | Production topology and threat model |

## Current gate decision

Haystack BM25 is the preferred next lexical candidate because the synthetic
fixture preserved Recall@10 `1.0` and Precision@10 `0.672807` while improving
MRR to `0.973684`. This does not unlock grounded answering: semantic retrieval,
authorized live evidence resolution and production acceptance remain `NOT
MEASURED`.
