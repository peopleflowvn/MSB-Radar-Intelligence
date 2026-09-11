# GreenNode Integration

GreenNode remains the primary inference platform. Radar Intelligence uses its
OpenAI-compatible `POST /chat/completions` contract through a small transport
owned by this service. Business modules select `FAST`, `DEEP`, `VISION`, or
`EMBEDDING`; only configuration maps those capabilities to concrete model
aliases.

Required runtime configuration will be supplied by the deployment environment
or Radar settings integration. API keys are never committed, logged, included
in traces, or copied from the legacy repository. Base URLs must use HTTPS.

The adapter validates response shape, carries request ID and token usage, uses
the caller's bounded timeout, and returns sanitized provider errors. Mocked
contract tests verify the outgoing OpenAI-compatible payload and malformed
response behavior. No GreenNode environment variables are currently present,
so live inference is `NOT TESTED` rather than treated as a development blocker.

The embedding adapter uses the OpenAI-compatible `POST /embeddings` contract,
validates vector count/order/dimensions at its consumers, and implements the
same injectable interface used by indexing and query embedding. Contract tests
use mocked HTTP responses; live embedding quality remains `NOT MEASURED`.
