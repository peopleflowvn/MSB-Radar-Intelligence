# Legacy Reuse Manifest

No legacy implementation has been copied in this milestone. Items marked
"candidate" require source-level review and dedicated equivalence tests before
reuse.

| Component | Legacy path | Category | Reason | Action | Dependency | Risk |
|---|---|---|---|---|---|---|
| Person/Identity ownership | `server/people/` | KEEP EXTERNAL | Business truth and high-cost merge decisions | Reference IDs only | Radar API | Cross-person leakage |
| SourceRecord/Document lifecycle | `server/core/` | KEEP EXTERNAL | Provenance and file truth belong to product | Consume versioned feed | Radar API/storage | Stale/deleted evidence |
| Talent/RB workflows | `server/talent/`, `server/rb/` | KEEP EXTERNAL | Consequential business state | Propose only | Product API | Unauthorized mutation |
| RBAC, quota, AccessLog | `server/accounts/` | KEEP EXTERNAL | Radar is authorization authority | Require authorized scope | Auth API | Scope bypass |
| Edge collectors/outbox | `edge/` | KEEP EXTERNAL | Local sessions and sync are operational product concerns | Subscribe after Hub ingest | Hub feed | Duplicate/out-of-order events |
| Vietnamese normalization | people/talent normalization utilities | REUSE / PORT CANDIDATE | Deterministic behavior is valuable | Review then reimplement/equivalence-test | Unicode rules | Semantic drift |
| Boolean query behavior | Talent search/parser tests | REUSE / PORT CANDIDATE | Verified exact behavior | Extract contract tests first | Search grammar | Query reinterpretation |
| Provider protocol/usage shapes | `server/ai/providers.py` | REUSE / PORT CANDIDATE | Stable transport concerns | Adapt concepts, no secret/config copy | GreenNode | Error/usage mismatch |
| Public search/answer behavior | Talent API and tests | REIMPLEMENT CONTRACT | Clients need stable behavior, not legacy internals | Define V2 schemas/adapters | Radar integration | Compatibility gap |
| Evidence/citation behavior | `server/talent/answer/`, tests | REIMPLEMENT CONTRACT | Evidence must be first-class and code-validated | New evidence engine | Source resolver | Fabricated citation |
| Conversation references | `server/ai/conversation.py`, Answer tests | REIMPLEMENT CONTRACT | Follow-up behavior is required | Bounded state contract after Q&A gate | State store | Cross-user context |
| GreenNode routing | `server/ai/router.py` | REIMPLEMENT CONTRACT | Capability routing is needed without business hard-coding | New gateway/router | Configuration | Cost/latency drift |
| PLAN/JUDGE/AGGREGATE/COMPOSE | `server/talent/answer/` | DO NOT PORT | Bespoke orchestration is explicitly superseded | Preserve only failure tests | None | Technical-debt transfer |
| StateGraph/agent loop | `server/ai/graph*.py`, `agent/` | DO NOT PORT | Agent is not P0 and must beat simple RAG | Reassess in P1 | Haystack tools | Needless complexity |
| Prompt/fallback maze | `server/ai/`, Answer internals | DO NOT PORT | Patch-driven semantics are not a clean contract | Replace with measured paths | Evaluation | Regression hidden by demos |
| Frontend/admin/settings UI | `web/` | KEEP EXTERNAL | Product-owned UX and configuration | Integration spec only | Product API | Split-brain configuration |
| Synthetic retrieval gold fixture | `server/ai/fixtures/brain_v2_gold.json` | REUSE / PORT TEST CONTRACT | Explicit fictional facts and expected IDs enable a safe comparable baseline | Read as immutable external fixture; record SHA-256; do not copy V1 retrieval code | Evaluation runner | Synthetic results could be mistaken for production quality |

## Synthetic retrieval gold fixture record

**SOURCE:** `D:\\Project\\MSB_Radar\\server\\ai\\fixtures\\brain_v2_gold.json`.

**PURPOSE:** Exercise V2 retrieval against the same fictional people and
explicit expected IDs used by the legacy benchmark.

**WHY REUSE:** It is a verified test contract, contains no production PII, and
supports an apples-to-apples deterministic baseline.

**DEPENDENCIES:** New V2 evaluation runner and retrieval contracts only.

**RISK:** Six synthetic people cannot establish production retrieval quality or
human acceptance.

**MODIFICATION:** The fixture is not copied or changed. V2 reads it by path and
records its SHA-256. Legacy query expansions are used as benchmark input.

**TEST:** The report records case-level expected/actual IDs, Recall@K,
Precision@K, MRR, no-result accuracy and latency. Semantic and production
quality remain `NOT MEASURED`.

## Required record for any future copied primitive

Add a row plus a detailed section containing: SOURCE, PURPOSE, WHY REUSE,
DEPENDENCIES, RISK, MODIFICATION, and TEST. A passing test is mandatory before
the copied code is merged.
