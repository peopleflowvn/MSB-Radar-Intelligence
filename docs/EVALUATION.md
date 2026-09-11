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
