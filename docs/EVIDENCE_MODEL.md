# Evidence Model

Evidence is a code-created object, never a citation label invented by a model.
Each item contains a stable evidence ID, Radar Person and Document IDs, source,
exact passage, source location, normalized score, content hash, document
version and deletion state.

## Lifecycle

1. Radar authorizes scope and supplies versioned document representations.
2. Indexing preserves `person_id`, `document_id`, version and content hash on
   every chunk.
3. Retrieval returns only chunks from authorized people and groups them by
   Person.
4. A context builder will assign existing evidence IDs to model context.
5. Model output may reference only those IDs.
6. Code rejects unknown, deleted or wrong-Person citations.
7. Before production display, a Radar source resolver must re-check scope,
   current version/hash and source availability.

## Fail-closed rules

- Unknown evidence ID: reject the citation.
- Deleted evidence: reject it even if stale index content remains.
- Evidence whose Person differs from the answer target: reject it.
- Version/hash drift: production resolver must return `STALE_EVIDENCE`.
- Empty evidence: no factual synthesis; return insufficient evidence.
- Prompt instructions inside a CV are untrusted document content, not system or
  user instructions.

All fail-closed rules now have code-side contract tests through an injected
`SourceResolver`: missing/unauthorized sources, Person reassignment and
version/hash drift are rejected before returning citations. The actual Radar
resolver endpoint is not implemented because its integration contract is not
yet agreed. Grounded answering remains gated on that live adapter.
