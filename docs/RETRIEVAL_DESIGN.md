# Retrieval Design

## Execution order

1. Resolve the opaque Radar scope into authorized Person IDs.
2. Remove unauthorized records before any retrieval or model component runs.
3. Apply reliable structured filters as hard constraints.
4. Run lexical and semantic retrieval over the remaining records.
5. Fuse ranks deterministically and group chunks by Person.
6. Return at most the requested number of people with their best evidence.

The semantic component receives only authorized, structured-filtered records.
It cannot introduce an evidence ID that was absent from its input. This keeps
permission enforcement deterministic and prevents a retriever or model from
broadening scope.

## Current implementations

- Structured: location, all-required skills, company, education, experience
  range and exclusions, with accent-insensitive Vietnamese normalization.
- Lexical: deterministic token overlap reference scorer.
- Semantic: cosine ranker over indexed vectors plus an injected query embedder;
  GreenNode's OpenAI-compatible embedding contract is implemented, but no live
  production embedding model has been measured.
- Hybrid: reciprocal-rank fusion followed by Person grouping.

The lexical scorer is a testable baseline, not a claim that token overlap is
production BM25. Haystack BM25/dense retrievers and a production store must be
benchmarked against explicit gold truth before selection.

## Quality gate

The gate requires explicit relevant Person IDs per evaluation case, Recall@K,
Precision@K and MRR. The existing 51 query seed lacks verified Person truth and
therefore cannot produce honest retrieval metrics yet. Metrics remain `NOT
MEASURED` until a stable authorized corpus snapshot is paired with reviewed
expected Person IDs.
