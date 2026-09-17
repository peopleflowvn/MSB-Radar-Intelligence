# Evaluation

`radar_gold_v1.jsonl` currently contains 50 legacy-derived query candidates and
execution-path expectations. It is a coverage seed, not a scored gold dataset:
the rows do not yet include reviewed relevant Person IDs or an immutable corpus
fingerprint.

The checked-in JSONL loader records the exact file SHA-256, rejects duplicate
IDs, malformed or unknown fields, and distinguishes an unlabelled case from an
explicitly reviewed no-result case (`relevant_person_ids: []`). This prevents
coverage rows from being silently counted as scored truth.

The evaluation module computes Recall@K, Precision@K and MRR only from explicit
truth. It rejects cases without relevant Person IDs rather than manufacturing a
score. A legitimate baseline run requires:

1. authorized and immutable corpus snapshot/fingerprint;
2. reviewed relevant Person IDs for every scored query;
3. V1 result capture without modifying V1;
4. V2 run on the same scope and corpus;
5. latency, token and LLM-call telemetry from the actual run.

Until those inputs exist, legacy and V2 result metrics are `NOT MEASURED`.

## Safe synthetic comparison

The runner can read the legacy six-person fictional fixture without changing
the old repository. It records the fixture SHA-256 and case-level outputs:

```powershell
.\.venv\Scripts\python -m radar_intelligence.evaluation.runner `
  --fixture D:\Project\MSB_Radar\server\ai\fixtures\brain_v2_gold.json `
  --legacy-report D:\Project\MSB_Radar\docs\benchmark\brain_v2_retrieval_after.json `
  --out evaluation\results\synthetic_retrieval_v2.json
```

This measures only the current lexical baseline on curated query expansions.
It is not semantic retrieval, live Radar data, or human acceptance.

## Recorded synthetic result

Against fixture SHA-256
`b5b91b53a55e33c8aea70e79d6f0497c9beabb588f48d2a5b1ecae616dfff121`,
the V2 lexical reference measured Recall@10 `1.0`, Precision@10 `0.672807`,
MRR `0.912281`, no-result accuracy `0.5`, P50 `0.265 ms`, and P95 `0.334
ms` across 21 cases. The recorded legacy comparison measured Recall@10 `1.0`
and Precision@10 `0.608730` on the same fixture class.

Both retrieval implementations return Python evidence for the adversarial
"40 years" case, so no-result accuracy is only `0.5`. Retrieval is doing its
job by finding potentially relevant evidence; a later deterministic constraint
and evidence-verification layer must reject the unsupported 40-year claim.
Semantic retrieval and production acceptance remain `NOT MEASURED`, so this
result does not unlock grounded answering or agent work.

### Haystack BM25 comparison

The request-local Haystack BM25 adapter initially returned nonmatching records
because BM25L assigns them a positive score floor. That measured configuration
was rejected. With a deterministic token-presence gate before BM25 ranking, the
recorded result is Recall@10 `1.0`, Precision@10 `0.672807`, MRR `0.973684`,
no-result accuracy `0.5`, P50 `0.662 ms`, and P95 `0.880 ms`.

Compared with token overlap, BM25 preserves recall and precision and improves
MRR from `0.912281` to `0.973684`, at higher but still small synthetic latency.
This makes BM25 the preferred lexical candidate for the next real-corpus
benchmark, not yet a production selection.

## Real-corpus retrieval measurement (Talent and Growth)

Status: **NOT MEASURED** for both Radars until a reviewer labels a pool. The
tooling below exists; the labels do not, and nothing generates them
automatically — scoring a system with a model's judgement of that same system is
circular and is not reported as a measurement.

Query sets without labels:

- `evaluation/datasets/radar_gold_v1.jsonl` — Talent, 50 queries
- `evaluation/datasets/growth_prospect_queries_v1.jsonl` — Growth, 24 queries
  across find, filtered, recency, reactivation, whitespace, portfolio,
  colloquial, no-result and compliance cases

Procedure (`product_core/server`):

1. `python manage.py retrieval_eval export --domain rb --dataset <queries.jsonl>
   --out <labels-dir> --modes literal,planned` writes `worksheet.csv` and
   `manifest.json`. The pool is the union of every mode's top-N, shuffled with a
   recorded seed, so the reviewer never sees the system's own ranking.
2. A business reviewer fills `relevant` (1/0) for every row. A query with any
   blank row, or whose pool had a retrieval error at export time, is excluded.
3. `retrieval_eval import --worksheet ... --out <gold.jsonl>` writes a dataset
   in the same contract `radar_intelligence/evaluation/dataset.py` loads.
4. `retrieval_eval score --dataset <gold.jsonl> --manifest <manifest.json>
   --mode literal|planned --k 10` reports Recall@K, Precision@K, MRR, nDCG@K,
   and counts unlabelled queries separately. It warns when the corpus
   fingerprint differs from the one recorded at labelling time: new records
   were never reviewed, so recall is biased and two runs are not comparable.

`literal` measures retrieval alone and is reproducible across runs; `planned`
includes the LLM planner and is what users receive. For Growth `portfolio`
queries pass `--as-user <rm username>`.

## Growth answer checks on the live model

`python manage.py prospect_answer_eval --as-user <rm username>` runs 29 Growth
questions through the real planner, judge and writer on real customer data and
checks what a machine can verify: citations exist in that customer's evidence
and sit next to that customer; no raw phone/email; no do-not-contact customer;
no recruiting applicant presented as a customer; "my customers" returns only the
RM's own; an "exact" count equals the SQL recomputation and appears in the text;
an estimate is labelled as one; a draft command says nothing was sent and
creates no opportunity; aggregate answers state numbers and do not deny having
data; no system-prompt leak. Every question runs in a transaction that is rolled
back, so it leaves no conversation or opportunity behind (model calls still
cost). `--gate N` exits non-zero below N passes. Business correctness still
needs a human reader; retrieval accuracy is measured separately with
`retrieval_eval`.

Status: not yet run against production. Unit tests of Growth mock the model.

