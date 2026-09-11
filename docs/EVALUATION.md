# Evaluation

`radar_gold_v1.jsonl` currently contains 51 legacy-derived query candidates and
execution-path expectations. It is a coverage seed, not a scored gold dataset:
the rows do not yet include reviewed relevant Person IDs or an immutable corpus
fingerprint.

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
