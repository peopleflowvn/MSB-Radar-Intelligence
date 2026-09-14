# Delivery Phase Status

Status is evidence-based: `DONE` means the stated deliverable exists and its
current automated checks pass; `PARTIAL` identifies the missing live or
production evidence explicitly.

| Phase | Status | Evidence | Remaining gate |
|---|---|---|---|
| 0 Legacy discovery | DONE | `LEGACY_SYSTEM_MAP.md`; legacy checkout read-only | Refresh map when legacy contracts change |
| 1 Reuse classification | DONE | `LEGACY_REUSE_MANIFEST.md`; every used legacy fixture is recorded | Record every future reused primitive |
| 2 Architecture/contracts | DONE | Framework-independent dataclasses, strict JSON codec, architecture and API contract | HTTP routing remains separate from the stable serialization boundary |
| 3 Gold Set/baseline | PARTIAL | 50 validated query coverage cases; 21 retrieval cases measured on hashed six-person synthetic fixture | Human-labelled real corpus and V1 run on identical authorized snapshot |
| 4 GreenNode gateway | PARTIAL | Capability routes, chat/embedding transport and mock contract tests | Live configured FAST/DEEP/VISION/EMBEDDING calls and telemetry |
| 5 Indexing | PARTIAL | Converter, metadata, replay/delete/reassignment; Haystack tests; feed client; checkpoint coordinator; restart-tested SQLite cursor and safe failure details | Product-side durable feed, shared production cursor/index store and reindex/delete SLA |
| 6 Retrieval | PARTIAL | Structured, token lexical, Haystack BM25, cosine semantic adapter, hybrid fusion and scope-before-retrieval tests | Live embedding benchmark on real labelled corpus |
| 7 Person reranking | PARTIAL | Person grouping, best-evidence selection, RRF and synthetic MRR measurement | Real-corpus reranking comparison and selected thresholds |
| 8 Evidence | PARTIAL | First-class evidence plus fail-closed citation, deletion, Person, scope and version/hash resolver contract tests | Authorized live Radar resolver adapter |
| 9 Grounded RAG | PARTIAL | Production `/v1/answer` runs the LangGraph scope/retrieve/generate/validate graph; live probe verifies the graph marker | Human-labelled faithfulness and multi-hop gates |
| 10 Conversation state | NOT STARTED | Contract only | Grounded Q&A gate |
| 11 Agent | NOT STARTED | Action contract only | Demonstrated multi-step need and RAG comparison |
| 12 Model benchmark | PARTIAL | Cross-provider fictional-data benchmark supports configured GreenNode, Gemini and OpenAI without route changes | Repeated production run plus human-labelled document-Q&A cases and cost data |
| 13 Legacy vs V2 | PARTIAL | Comparable synthetic lexical report | Same real corpus, scope and telemetry |
| 14 Radar integration | DONE | Production document feed, evidence resolver, scope validation, V2 search bridge and Person-level multi-query RRF are tested and live-probed | Continue regression monitoring |
| 15 Hardening | PARTIAL | Fail-closed tests; HTTPS config validation; separate liveness/readiness; allow-listed operational trace without query, scope token, evidence text or chain-of-thought | Production topology, threat model, load/failure drills, trace sink and alerting |

## Current gate decision

Haystack BM25 is the preferred next lexical candidate because the synthetic
fixture preserved Recall@10 `1.0` and Precision@10 `0.672807` while improving
MRR to `0.973684`. Grounded answering and production connectivity are now live,
but semantic retrieval and answer quality still require a human-labelled
real-corpus comparison; production connectivity alone is not a NotebookLM-level
quality claim.
