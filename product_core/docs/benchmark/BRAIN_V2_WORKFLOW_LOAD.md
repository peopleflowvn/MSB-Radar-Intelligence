# Workflow and bounded HTTP probes

The five-turn HTTP/SSE regression exercises real conversation persistence and
projection: initial result, first-two comparison, second-person detail, replacement
search, and a second-person question against the replacement. A separate conversation
must start with no inherited result. Model/engine output is mocked; this is not live
model correctness or browser acceptance.

It exposed a routing gap: an explicit positional follow-up without a question mark
could miss the corpus heuristic and leave the previous result unchanged. The stream
gate now considers explicit references to persisted results and search intent. CV
permission and the non-fallback planner decision still gate entry to the engine.

`scripts/brain_http_load.py` probes a supplied Assistant SSE endpoint with at most
20 requests and concurrency 4. Each request uses a new conversation and therefore
creates persisted test turns. Use a dedicated test account and corpus. Credentials
come from `BRAIN_LOAD_COOKIE`, `BRAIN_LOAD_CSRF`, or `BRAIN_LOAD_AUTHORIZATION`.
Redirects are refused. Output omits credentials, question and answer content.

Example against a locally running server:

```powershell
python scripts/brain_http_load.py --url http://127.0.0.1:8000/api/v1/ai/assistant/stream/ --question "Tìm ứng viên biết SQL" --requests 4 --concurrency 2 --out docs/benchmark/label_batch/http-load.json
```

The report records completion/error, first-answer latency, total latency, successful
P50/P95 and throughput. An error followed by done is not a success; EOF without done
is incomplete. A done event is protocol completion, not semantic acceptance. Timeout
is checked between received lines and applied to socket reads, not forcible thread
cancellation; a pending read can extend beyond the elapsed-time check.

Loopback fixture tests cover success, SSE error, truncated output and percentiles.
No deployed load measurement or live five-turn model run has been performed in this
increment. Those gates remain open alongside recruiter review, PostgreSQL/vector
acceptance, scanned CV evidence, and provider cancellation.
