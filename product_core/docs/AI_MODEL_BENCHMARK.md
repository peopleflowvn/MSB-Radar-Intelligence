# GreenNode model benchmark — Brain V2

Dates: 2026-09-07 to 2026-09-08. Live provider calls, fictional gold v1. **Small task probes, not production acceptance.**
No saved task routes, provider settings or credentials were changed. The original run discovered seven models;
the conversation rerun discovered ten. Two newly listed GLM models received the remaining 14 probes each;
bge-m3 is an embedding model and its initial conversation failure is not an embedding benchmark.

## Method and audit trail

105 initial probes (7 models × 15 cases across 8 task groups). Seven conversation probes failed in the harness
before calling a model: build_conversation_request returns a tuple. Corrected and reran conversation against
the newly returned inventory. Raw evidence is retained; corrected scoring is in brain_v2_models_scored.json.
Fallback plan output is not credited as model accuracy. Missing judge rows are a failed completeness contract,
even when an empty returned list happens to match expected_ids=[]. Retries count as attempts and tokens.

Actual plan/judge/extraction/compose/conversation code and prompts were used. Intent uses the runtime rubric
to isolate model classification from provider-independent guards. Outreach and vision are isolated template
probes (draft text and a tiny synthetic PNG), not full messaging/scanned-CV acceptance. No real messages were sent.
The first run predates numeric-provenance/telemetry additions. Eight later Qwen Flash/Plus judge probes
are retained separately in brain_v2_judge_after.json (all eight exact-ID contracts passed). They do not
establish semantic entailment or a production-quality gain. No default changed from this small sample.

`Pass` below means the narrow machine-checkable task contract completed without failed/truncated attempts.
It does not measure all semantic correctness. n=1 P50=P95 is one observation, not a production percentile.
Token totals include only reported usage; failed attempts may have unreported billing. Cost: **NOT MEASURED**.

## Results by task

### compose

| Model | Pass/n | Attempts/errors/cut | P50/P95 ms | Known input/output tokens | Unknown usage |
|---|---:|---:|---:|---:|---:|
| z-ai/glm-5.2-hackathon | 1/1 | 1/0/0 | 6056.54/6056.54 | 1730/67 | 0 |
| qwen/qwen3.6-plus | 1/1 | 1/0/0 | 2408.93/2408.93 | 1637/71 | 0 |
| qwen/qwen3.6-flash | 1/1 | 1/0/0 | 1084.08/1084.08 | 1637/52 | 0 |
| google/gemma-4-31b-it | 0/1 | 1/1/0 | 203.98/203.98 | 0/0 | 1 |
| qwen/qwen3.7-plus | 0/1 | 1/1/0 | 1205.68/1205.68 | 0/0 | 1 |
| deepseek/deepseek-v4-flash | 1/1 | 1/0/0 | 5476.75/5476.75 | 2258/484 | 0 |
| deepseek/deepseek-v4-pro | 1/1 | 1/0/0 | 8604.18/8604.18 | 2258/453 | 0 |
| z-ai/glm-5.3-flash-thirdparty | 0/1 | 1/1/0 | 135.5/135.5 | 0/0 | 1 |
| z-ai/glm-5.2-thirdparty | 1/1 | 1/0/0 | 5444.55/5444.55 | 1827/252 | 0 |

### conversation

| Model | Pass/n | Attempts/errors/cut | P50/P95 ms | Known input/output tokens | Unknown usage |
|---|---:|---:|---:|---:|---:|
| z-ai/glm-5.2-hackathon | 1/1 | 1/0/0 | 11624.09/11624.09 | 289/190 | 0 |
| qwen/qwen3.6-plus | 1/1 | 1/0/0 | 4379.82/4379.82 | 276/185 | 0 |
| qwen/qwen3.6-flash | 1/1 | 1/0/0 | 5428.68/5428.68 | 276/283 | 0 |
| google/gemma-4-31b-it | 0/1 | 1/1/0 | 144.94/144.94 | 0/0 | 1 |
| qwen/qwen3.7-plus | 1/1 | 1/0/0 | 3968.97/3968.97 | 276/180 | 0 |
| deepseek/deepseek-v4-flash | 1/1 | 1/0/0 | 5415.55/5415.55 | 403/481 | 0 |
| deepseek/deepseek-v4-pro | 1/1 | 1/0/0 | 10000.8/10000.8 | 403/589 | 0 |
| z-ai/glm-5.3-flash-thirdparty | 0/1 | 1/1/0 | 381.75/381.75 | 0/0 | 1 |
| z-ai/glm-5.2-thirdparty | 0/1 | 1/0/1 | 11883.38/11883.38 | 295/600 | 0 |
| baai/bge-m3 | 0/1 | 1/1/0 | 127.08/127.08 | 0/0 | 1 |

### extraction

| Model | Pass/n | Attempts/errors/cut | P50/P95 ms | Known input/output tokens | Unknown usage |
|---|---:|---:|---:|---:|---:|
| z-ai/glm-5.2-hackathon | 1/1 | 1/0/0 | 6255.71/6255.71 | 369/90 | 0 |
| qwen/qwen3.6-plus | 1/1 | 1/0/0 | 2878.23/2878.23 | 342/103 | 0 |
| qwen/qwen3.6-flash | 1/1 | 1/0/0 | 1069.0/1069.0 | 342/103 | 0 |
| google/gemma-4-31b-it | 0/1 | 1/1/0 | 224.0/224.0 | 0/0 | 1 |
| qwen/qwen3.7-plus | 0/1 | 1/1/0 | 185.93/185.93 | 0/0 | 1 |
| deepseek/deepseek-v4-flash | 1/1 | 1/0/0 | 4479.97/4479.97 | 463/423 | 0 |
| deepseek/deepseek-v4-pro | 1/1 | 1/0/0 | 8167.84/8167.84 | 463/478 | 0 |
| z-ai/glm-5.3-flash-thirdparty | 0/1 | 1/1/0 | 131.51/131.51 | 0/0 | 1 |
| z-ai/glm-5.2-thirdparty | 1/1 | 1/0/0 | 11653.23/11653.23 | 428/800 | 0 |

### intent

| Model | Pass/n | Attempts/errors/cut | P50/P95 ms | Known input/output tokens | Unknown usage |
|---|---:|---:|---:|---:|---:|
| z-ai/glm-5.2-hackathon | 2/2 | 2/0/0 | 10068.73/11929.5 | 524/355 | 0 |
| qwen/qwen3.6-plus | 2/2 | 2/0/0 | 12543.22/15694.5 | 498/1354 | 0 |
| qwen/qwen3.6-flash | 2/2 | 2/0/0 | 5482.01/6294.78 | 498/1010 | 0 |
| google/gemma-4-31b-it | 2/2 | 2/0/0 | 738.89/787.41 | 525/89 | 0 |
| qwen/qwen3.7-plus | 2/2 | 2/0/0 | 12739.3/14129.93 | 498/1391 | 0 |
| deepseek/deepseek-v4-flash | 2/2 | 2/0/0 | 2173.59/2196.1 | 689/298 | 0 |
| deepseek/deepseek-v4-pro | 1/2 | 2/0/1 | 4235.44/4300.52 | 689/343 | 0 |
| z-ai/glm-5.3-flash-thirdparty | 0/2 | 2/2/0 | 132.42/139.83 | 0/0 | 2 |
| z-ai/glm-5.2-thirdparty | 0/2 | 2/0/2 | 4087.57/4272.04 | 630/360 | 0 |

### judge

| Model | Pass/n | Attempts/errors/cut | P50/P95 ms | Known input/output tokens | Unknown usage |
|---|---:|---:|---:|---:|---:|
| z-ai/glm-5.2-hackathon | 4/4 | 6/0/0 | 20218.15/32517.58 | 6179/2798 | 0 |
| qwen/qwen3.6-plus | 4/4 | 4/0/0 | 13750.94/15184.15 | 4296/3018 | 0 |
| qwen/qwen3.6-flash | 4/4 | 4/0/0 | 5390.93/5455.03 | 4296/3444 | 0 |
| google/gemma-4-31b-it | 0/4 | 12/12/0 | 487.78/496.07 | 0/0 | 12 |
| qwen/qwen3.7-plus | 4/4 | 4/0/0 | 14513.86/15484.96 | 4296/3128 | 0 |
| deepseek/deepseek-v4-flash | 3/4 | 6/1/0 | 21889.54/45455.46 | 6355/9027 | 1 |
| deepseek/deepseek-v4-pro | 1/4 | 10/6/0 | 66757.57/72447.82 | 4766/5039 | 6 |
| z-ai/glm-5.3-flash-thirdparty | 0/4 | 12/12/0 | 720.22/1111.19 | 0/0 | 12 |
| z-ai/glm-5.2-thirdparty | 3/4 | 6/2/0 | 18160.18/46358.92 | 4415/4241 | 2 |

### outreach

| Model | Pass/n | Attempts/errors/cut | P50/P95 ms | Known input/output tokens | Unknown usage |
|---|---:|---:|---:|---:|---:|
| z-ai/glm-5.2-hackathon | 1/1 | 1/0/0 | 7582.41/7582.41 | 58/130 | 0 |
| qwen/qwen3.6-plus | 1/1 | 1/0/0 | 1994.84/1994.84 | 61/72 | 0 |
| qwen/qwen3.6-flash | 1/1 | 1/0/0 | 1457.92/1457.92 | 61/76 | 0 |
| google/gemma-4-31b-it | 0/1 | 1/1/0 | 166.98/166.98 | 0/0 | 1 |
| qwen/qwen3.7-plus | 0/1 | 1/1/0 | 154.56/154.56 | 0/0 | 1 |
| deepseek/deepseek-v4-flash | 0/1 | 1/0/1 | 7633.48/7633.48 | 79/701 | 0 |
| deepseek/deepseek-v4-pro | 0/1 | 1/0/1 | 12433.15/12433.15 | 79/701 | 0 |
| z-ai/glm-5.3-flash-thirdparty | 0/1 | 1/1/0 | 117.38/117.38 | 0/0 | 1 |
| z-ai/glm-5.2-thirdparty | 0/1 | 1/0/1 | 11287.59/11287.59 | 64/700 | 0 |

### plan

| Model | Pass/n | Attempts/errors/cut | P50/P95 ms | Known input/output tokens | Unknown usage |
|---|---:|---:|---:|---:|---:|
| z-ai/glm-5.2-hackathon | 4/4 | 4/0/0 | 7780.4/9284.91 | 6079/633 | 0 |
| qwen/qwen3.6-plus | 4/4 | 4/0/0 | 3847.05/4377.81 | 5738/672 | 0 |
| qwen/qwen3.6-flash | 4/4 | 4/0/0 | 1937.24/2257.95 | 5738/741 | 0 |
| google/gemma-4-31b-it | 0/4 | 4/4/0 | 167.19/184.36 | 0/0 | 4 |
| qwen/qwen3.7-plus | 4/4 | 4/0/0 | 4486.08/4938.87 | 5738/729 | 0 |
| deepseek/deepseek-v4-flash | 1/4 | 4/0/3 | 8863.54/9179.47 | 7982/3539 | 0 |
| deepseek/deepseek-v4-pro | 0/4 | 4/0/4 | 14944.07/16101.04 | 7982/3604 | 0 |
| z-ai/glm-5.3-flash-thirdparty | 0/4 | 4/4/0 | 410.64/684.05 | 0/0 | 4 |
| z-ai/glm-5.2-thirdparty | 4/4 | 4/0/0 | 7038.57/8865.65 | 6383/1720 | 0 |

### tool_call

| Model | Pass/n | Attempts/errors/cut | P50/P95 ms | Known input/output tokens | Unknown usage |
|---|---:|---:|---:|---:|---:|
| z-ai/glm-5.2-hackathon | 1/1 | 1/0/0 | 4007.44/4007.44 | 269/43 | 0 |
| qwen/qwen3.6-plus | 1/1 | 1/0/0 | 1700.32/1700.32 | 383/28 | 0 |
| qwen/qwen3.6-flash | 1/1 | 1/0/0 | 604.27/604.27 | 383/28 | 0 |
| google/gemma-4-31b-it | 0/1 | 1/1/0 | 139.05/139.05 | 0/0 | 1 |
| qwen/qwen3.7-plus | 1/1 | 1/0/0 | 1936.43/1936.43 | 383/53 | 0 |
| deepseek/deepseek-v4-flash | 1/1 | 1/0/0 | 2130.83/2130.83 | 425/141 | 0 |
| deepseek/deepseek-v4-pro | 1/1 | 1/0/0 | 2793.63/2793.63 | 425/100 | 0 |
| z-ai/glm-5.3-flash-thirdparty | 0/1 | 1/1/0 | 424.74/424.74 | 0/0 | 1 |
| z-ai/glm-5.2-thirdparty | 0/1 | 1/0/0 | 5415.82/5415.82 | 269/42 | 0 |

### vision

| Model | Pass/n | Attempts/errors/cut | P50/P95 ms | Known input/output tokens | Unknown usage |
|---|---:|---:|---:|---:|---:|
| z-ai/glm-5.2-hackathon | 0/1 | 1/1/0 | 658.07/658.07 | 0/0 | 1 |
| qwen/qwen3.6-plus | 1/1 | 1/0/0 | 2079.89/2079.89 | 137/14 | 0 |
| qwen/qwen3.6-flash | 1/1 | 1/0/0 | 2005.57/2005.57 | 137/14 | 0 |
| google/gemma-4-31b-it | 0/1 | 1/1/0 | 159.49/159.49 | 0/0 | 1 |
| qwen/qwen3.7-plus | 0/1 | 1/1/0 | 161.69/161.69 | 0/0 | 1 |
| deepseek/deepseek-v4-flash | 0/1 | 1/0/0 | 1627.97/1627.97 | 13/70 | 0 |
| deepseek/deepseek-v4-pro | 0/1 | 1/0/1 | 9712.36/9712.36 | 13/501 | 0 |
| z-ai/glm-5.3-flash-thirdparty | 0/1 | 1/1/0 | 251.66/251.66 | 0/0 | 1 |
| z-ai/glm-5.2-thirdparty | 0/1 | 1/1/0 | 653.43/653.43 | 0/0 | 1 |

## Conditional-count continuation

Repeated live Qwen 3.6 Flash count workflows exposed both semantic false positives and schema omissions. [Continuation report](benchmark/BRAIN_V2_COUNTS.md) records the stricter evidence contract, remaining risks and measured token/latency cost. These are separate probes, not additions to the original 145-row model comparison; task defaults remain unchanged.

## Routing recommendation

- FAST plan/judge/extraction: retain Qwen 3.6 Flash as the existing default; Qwen 3.6 Plus is a candidate override. The probes support feasibility, not a universal winner.
- DEEP compose: keep the configured DeepSeek V4 Pro route pending a broader difficult-comparison/composition gold set. One source-backed answer cannot establish best prose quality.
- Tight output budgets: do not move FAST/conversation/outreach to DeepSeek by default; measured truncation/fallback behavior is workload dependent.
- VISION: Qwen 3.6 Flash/Plus transcribed the fixture fields. Require real scanned-CV multilingual/OCR evaluation before claiming scan accuracy. A model appearing in /models does not establish vision capability.
- EMBEDDING: retain current specialized model and index dimensions. No dense retrieval/cost comparison measured here. The newly listed bge-m3 was encountered in an unfiltered conversation inventory probe; its chat failure says nothing about embedding quality.
- Tool calling: nine single-call probes use the actual evidence tool schema and 900-token agent budget; correctness requires the expected function and ordinal-resolved ID. This measures protocol only. Actual handler permissions/selection and multi-turn SSE persistence are covered separately by regression tests.

## Remaining evaluation work

Human-labelled production IDs and semantic evidence entailment; real PostgreSQL Recall@K; end-to-end HTTP/SSE follow-up chain; repeated cold/warm token and latency measurements; cost rate card; embedding comparison; tool-call protocol; real scanned CVs. Gold case coverage is not the same as executed acceptance coverage.
