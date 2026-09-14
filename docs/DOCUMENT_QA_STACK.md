# Document Q&A stack decision

The production objective is grounded, permission-safe document Q&A. Framework
count is not a quality metric; every component must improve a labelled Radar
evaluation before it becomes primary.

| Layer | Selected | Role | Production decision |
|---|---|---|---|
| Parsing | Existing Product Core extraction; Docling adapter | Preserve document structure before indexing | Docling remains offline until original-file ingestion and page-level provenance are available |
| Chunking | Structure-preserving bounded paragraph packing | Avoid isolated CV field lines while keeping traceable document chunks | Active for new/rebuilt Intelligence indexes |
| Retrieval | Haystack BM25 + dense embeddings + structured constraints | High-recall candidate generation | Active |
| Query expansion | Planner variants + person-level RRF | Retrieve Vietnamese/English synonyms and different formulations | Active, bounded to four parallel variants |
| Orchestration | LangGraph | Explicit authorization, retrieval, empty-evidence and grounded-answer branches | Active for Intelligence `/v1/answer` |
| Evaluation | Deterministic gates + optional Ragas | Retrieval/citation/faithfulness regression evidence | Deterministic gates active; Ragas offline only |
| Observability | Existing safe traces + optional Langfuse | Latency/fallback/quality analysis without CV or prompt payloads | Langfuse integration ready, disabled until a controlled self-host exists |

## Candidates that must earn adoption

- Qdrant dense+sparse+ColBERT multi-stage retrieval is the preferred scale and
  reranking experiment. It does not replace the current index until it improves
  real-corpus Recall@K/MRR, stays within the production latency budget and
  preserves scope-before-retrieval and deletion semantics.
- `BAAI/bge-reranker-v2-m3` is the preferred multilingual cross-encoder trial.
  Its model footprint and CPU latency make an unmeasured Oracle deployment
  unsafe; benchmark it on a separate inference process against the current RRF.
- DSPy prompt optimization may be evaluated only after a human-labelled gold
  set exists. Optimizing against synthetic or LLM-graded cases would overfit a
  proxy rather than improve recruiter answers.
- LlamaIndex, a second agent framework, and a second observability platform are
  rejected for now because they duplicate selected responsibilities without an
  identified quality gap.

## Model policy

GreenNode is a gateway and model catalogue, not one intelligence level. Compare
the exact GreenNode-hosted model with direct Gemini and direct OpenAI on the
same fictional/human-approved cases. The repository command
`brain_model_benchmark` accepts multiple configured providers, never changes
routes and never sends real CVs. A route may change only after quality, failure
rate, p50/p95 latency, token use and data-governance requirements are recorded.
