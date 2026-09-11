# Model Capability Routing

Public and business APIs select capabilities, never model names:

| Capability | Intended work |
|---|---|
| FAST | Query normalization, small extraction and lightweight planning |
| DEEP | Difficult comparison and evidence synthesis |
| VISION | Scanned or image-based documents |
| EMBEDDING | Index and query vectors |

`ModelGateway` requires all four routes at startup. Model aliases are deployment
configuration and may change without changing Search/Answer contracts. Timeout,
token usage, provider, alias and request ID are carried as trace data. Costlier
capabilities are enabled only when evaluation shows a material gain.
