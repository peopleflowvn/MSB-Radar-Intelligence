# Architecture decision: clean service boundary

Radar sends authenticated, already-authorized scope plus stable references.
Intelligence chooses a deterministic fast path or builds a small evidence
package using person-grouped hybrid retrieval. Models can interpret and
synthesize, but code validates scope, sources, citations, and actions.

The grounded-answer path is a LangGraph state graph: authorize and constrain
scope, retrieve with the Haystack-backed hybrid adapter, branch explicitly on
missing evidence, generate, then validate every cited source. Framework state
does not cross the API boundary. Product Core remains responsible for user
conversation, RBAC and business actions.

Product Core may send up to four independently phrased planner queries to the
search API in parallel. Results are fused by Person with reciprocal-rank fusion;
a failed variant is discarded without discarding successful variants. This
restores query expansion that previously stopped at the Intelligence bridge.

Langfuse tracing is disabled by default and enabled only when all three
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` values are
present. Spans contain counts and execution classes only, never questions,
candidate data, evidence text, scope tokens, prompts or model reasoning.

The public contracts contain no Haystack or model-specific types. Haystack will
be an internal adapter behind indexing/retrieval protocols. PostgreSQL remains
the business source of truth; an index is disposable and rebuildable.

## Delivery gates

1. Legacy map, reuse manifest, contracts, and >=50 gold cases.
2. Authorized document-feed contract and indexing idempotency/delete tests.
3. Structured, lexical, semantic, hybrid and person-grouping benchmarks.
4. Evidence accuracy and grounded Q&A gates.
5. Bounded conversation state.
6. Agent tools only for tasks that demonstrably require multi-step execution.

Safety failures (scope escape, wrong-person evidence, deleted evidence, prompt
injection obedience, or unapproved action) have zero tolerance.

## Current indexing boundary

`DocumentChange` is the versioned input from Radar. `DocumentConverter` creates
search-only chunks whose metadata always maps back to Radar Person and Document
IDs. `IncrementalIndexer` applies embeddings through an injected capability and
atomically replaces a document representation. The reference in-memory store
defines replay, stale-event, delete-tombstone and Person-reassignment behavior;
a Haystack adapter must preserve these tests before it can replace the store.

The first adapter targets Haystack's `DocumentStore` contract and has verified
parity for upsert/replay, version replacement, deletion and Person reassignment
using Haystack 3's real in-memory store. This is an integration reference, not
a production persistence choice; store durability and transaction behavior
remain a later benchmark/deployment decision.
