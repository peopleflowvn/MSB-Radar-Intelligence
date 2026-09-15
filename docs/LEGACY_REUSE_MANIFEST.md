# Legacy Reuse Manifest

No legacy implementation was copied in the initial clean-room milestone. Items marked
"candidate" require source-level review and dedicated equivalence tests before
reuse.

| Component | Legacy path | Category | Reason | Action | Dependency | Risk |
|---|---|---|---|---|---|---|
| Person/Identity ownership | `server/people/` | KEEP EXTERNAL | Business truth and high-cost merge decisions | Reference IDs only | Radar API | Cross-person leakage |
| SourceRecord/Document lifecycle | `server/core/` | KEEP EXTERNAL | Provenance and file truth belong to product | Consume versioned feed | Radar API/storage | Stale/deleted evidence |
| Talent/RB workflows | `server/talent/`, `server/rb/` | KEEP EXTERNAL | Consequential business state | Propose only | Product API | Unauthorized mutation |
| RBAC, quota, AccessLog | `server/accounts/` | KEEP EXTERNAL | Radar is authorization authority | Require authorized scope | Auth API | Scope bypass |
| Edge collectors/outbox | `edge/` (tracked at `product_core/edge/`) | KEEP EXTERNAL | Local sessions and sync are operational product concerns | Subscribe after Hub ingest | Hub feed | Duplicate/out-of-order events |
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

## Production ownership transition (2026-09-12)

**SOURCE:** MSB-Radar commit `a318ece41fef7b4f1b081b6a8736d8f892e1e9fd`.

**PURPOSE:** Preserve the existing React UI, Django authentication, RBAC,
settings, admin and business/data contracts while making this repository the
only production release source on Oracle.

**WHY REUSE:** The user explicitly requires the existing product surface and
data to remain unchanged, but no production checkout or deployment workflow may
depend on the legacy repository.

**DEPENDENCIES:** Existing PostgreSQL/R2 volumes and environment-owned secrets.

**RISK:** Product Core is a large compatibility snapshot. Legacy AI modules may
remain present but production routing must force Intelligence V2; future Product
Core changes must be made and tested here.

**MODIFICATION:** Tracked `server/`, `web/`, `.env.example`, `Caddyfile` and
Oracle compose sources are stored under `product_core/`. No secret or runtime
file is copied.

**TEST:** Run the original Django/React checks from `product_core/`, the
Intelligence suite, exact-SHA deployment checks, live auth/health, scope,
indexing, search and grounded-answer probes before removing legacy runtime files.

## Edge desktop collector tracked in this repository (2026-09-15)

**SOURCE:** `D:\\Project\\MSB_Radar\\edge\\` (PyWebView desktop app: recruitment-site
session/collection providers, local SQLite outbox, Hub sync client).

**PURPOSE:** Product Core (`product_core/server/core/`) already implements the
Hub-side `/api/v1/edge/{register,health,sync,data-report,documents}` endpoints
the Edge sync client (`app/sync/client.py`) calls, but the Edge source itself
had no durable copy inside this repository — only an untracked, gitignored
staging checkout (`.tmp-msb-radar-bootstrap/edge/`). Without a tracked source,
the edge-to-hub pipeline was incomplete: the Hub could accept Edge traffic but
this repository could not build, review or ship the client that produces it,
and production would depend on the legacy `MSB_Radar` checkout in violation of
the production-ownership-transition rule below.

**WHY REUSE:** Edge is explicitly KEEP EXTERNAL (local recruitment-site
sessions and sync are an operational product concern, not an Intelligence
retrieval concern). Verified byte-identical (diff -b -B) against
`MSB_Radar/edge/` before copying; only line endings differed. No `.env`,
`*.db*`, `chrome_profile/`, `trang-chi-tiet-ung-vien/`, `cauhinh*.json` or log
file was present in the staging checkout, and a secret-pattern scan of the
copied tree found only test-fixture placeholder credentials.

**DEPENDENCIES:** Hub edge endpoints (`product_core/server/core/urls.py`,
`views.py`); Edge's own `requirements.txt`/`pyproject.toml` (still targets
Python 3.9+, independent of the Intelligence service's Python 3.14 runtime).

**RISK:** Edge and Hub can silently drift if `SYNC_ENDPOINT`/`REGISTER_ENDPOINT`
request/response shapes change on one side without the other; there is no
contract test in this repository exercising them end-to-end yet.

**MODIFICATION:** Copied verbatim to `product_core/edge/`, alongside
`product_core/server/` and `product_core/web/`. No source line changed.

**TEST:** `core/tests_edge_admin.py` and the edge-endpoint views in
`product_core/server/core/` cover the Hub side. On copy, the sync/network
subset of `product_core/edge/tests/` (124 cases: `test_sync_foundation.py`,
`test_sync_service.py`, `test_net.py`, `test_request_jitter.py`,
`test_geo.py`, `test_state_paths.py`) was run under Python 3.9 with only
`pytest`/`requests`/`beautifulsoup4` installed and passed; the full suite
needs the heavier `requirements-dev.txt` (selenium, pywebview, pythonnet) and
has not been run from this repository, and no test yet exercises Edge against
a live Hub instance.

## Web-search fallback ported into Intelligence (2026-09-15)

**SOURCE:** `product_core/server/ai/websearch.py` (backend router: SearXNG,
DuckDuckGo, Tavily, Brave, Google CSE, Gemini grounding), plus the guard
concepts in `ai/pii.py` and `ai/prompt_guard.py`.

**PURPOSE:** Product Core already answers out-of-corpus questions from the web
(`ASSISTANT_WEB_SEARCH` defaults to `1` in `docker-compose.oracle-core.yml`,
DuckDuckGo needs no key). Intelligence V2's grounded path had no such fallback:
it returned "không tìm thấy bằng chứng" and stopped. Once V2 becomes the only
answer path, that would be a capability regression against what production does
today.

**WHY REUSE:** The backend-priority design (keyless autonomous backends first,
keyed ones next, a self-answering grounded backend last) is already proven in
production, and re-deriving it would risk a worse chain. Behavior parity also
means switching a surface between the two engines does not change what a user
can ask.

**DEPENDENCIES:** `ModelGateway` (Capability.FAST) for synthesizing raw snippet
results; no new package — urllib only, matching `providers/greennode.py`.

**RISK:** DuckDuckGo's HTML endpoint is unofficial and can rate-limit a server
IP or change markup; the chain falls through to the next backend, and a total
failure degrades to the original no-evidence answer. Web content is untrusted
input: it is wrapped in guard delimiters, and a question carrying PII or an
injection pattern never reaches a web backend at all.

**MODIFICATION:** Rewritten, not copied — `radar_intelligence/websearch/` is
framework-independent (no Django settings), config comes from a frozen
`WebSearchConfig.from_env`, transports are injectable, and results are returned
as an explicitly non-grounded answer (`interpreted_query.grounded == false`,
`source == "web"`) so a client can never present a web answer as CV evidence.

**TEST:** `tests/test_websearch_backends.py`, `tests/test_websearch_guard.py`,
`tests/test_websearch_service.py`, and the fallback wiring in
`tests/test_search_service_generation.py` (including "a PII question never
reaches a web backend"). No live network call in any test.

## Internal knowledge base (2026-09-15)

**SOURCE:** New — `product_core/server/knowledge/` (`KnowledgeDocument`), not
derived from legacy code.

**PURPOSE:** Let staff add internal policies/procedures/decisions on the Hub so
Radar answers those from the actual document instead of the model's general
knowledge.

**WHY NOT `people.Person`:** `Person` explicitly models a real human (its own
docstring, and `is_applicant`/merge/dedup logic depend on it). Representing a
policy document as a fake Person would corrupt applicant counts, duplicate
detection and merge decisions. A separate model with no FK to `Person` avoids
all of it.

**DEPENDENCIES:** `core/storage.py` (content-addressed storage shared with CVs),
`accounts/roles.py` (new `MODULE_KNOWLEDGE`, default Admin only, widened per
role through the existing `RoleModuleAccess` override table).

**RISK:** Two enforcement points must stay in agreement — `knowledge_ids` on the
request, and the module re-check in `evidence_document` at citation time. A hard
DELETE of a row emits no delete event (the feed is a single stream over live
rows), so retracting a document must use `is_active=False`. Scope tokens still
require `MODULE_TALENT`, so a knowledge-only role cannot use this yet (see
`talent/intelligence_client.knowledge_search`).

**MODIFICATION:** Indexed through the existing pipeline with a negative
`radar_entity_id` used as both person_id and document_id; negative ids cannot
collide with Django pks, so `int()`-based callers keep working unchanged.
Contract additions on the Intelligence side are additive and default to the
previous behavior: `person_ids`, `knowledge_ids` (opt-in only), `knowledge_only`.

**TEST:** `knowledge/tests.py`, `talent/tests_intelligence.py`
(`KnowledgeIntelligenceBridgeTest`), `talent/tests_intelligence_client.py`,
`ai/tests_knowledge_context.py`, plus `tests/test_search_service_generation.py`
(`KnowledgeIdsScopingTest`) and `tests/test_api_codec.py` on the V2 side.

## Required record for any future copied primitive

Add a row plus a detailed section containing: SOURCE, PURPOSE, WHY REUSE,
DEPENDENCIES, RISK, MODIFICATION, and TEST. A passing test is mandatory before
the copied code is merged.
