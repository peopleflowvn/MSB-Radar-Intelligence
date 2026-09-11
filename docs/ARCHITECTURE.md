# Architecture decision: clean service boundary

Radar sends authenticated, already-authorized scope plus stable references.
Intelligence chooses a deterministic fast path or builds a small evidence
package using person-grouped hybrid retrieval. Models can interpret and
synthesize, but code validates scope, sources, citations, and actions.

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

