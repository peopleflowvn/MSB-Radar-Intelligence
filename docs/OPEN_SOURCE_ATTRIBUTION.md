# Open Source Attribution

| Dependency | Source | Version policy | License | Intended use |
|---|---|---|---|---|
| Haystack | `https://github.com/deepset-ai/haystack` | `>=3.1,<4` (optional) | Apache-2.0 | Internal indexing/retrieval adapters and later evaluated pipelines |
| LangGraph | `https://github.com/langchain-ai/langgraph` | `>=1.2,<2` | MIT | Grounded-answer state graph and safe control-flow branches |
| Langfuse | `https://github.com/langfuse/langfuse` | `>=4.15,<5` (production extra) | MIT | Opt-in self-hosted metadata-only AI tracing |
| Ragas | `https://github.com/explodinggradients/ragas` | `>=0.4,<0.5` (evaluation extra) | Apache-2.0 | Offline grounded-answer quality evaluation |
| Docling | `https://github.com/docling-project/docling` | `>=2.126,<3` (documents extra) | MIT | Offline document conversion before controlled ingestion |

Haystack is open-source infrastructure, not MSB Radar business IP. The current
reference index is framework-independent and exists to test lifecycle and
security semantics before selecting a production document store.

Haystack 3 requires Python 3.10 or newer. Haystack 3.1.1 is installed in the
project-local Python 3.14 environment and the indexing adapter is integration
tested against its real in-memory document store. No production store has been
selected or claimed as verified. Ragas and Docling are intentionally isolated
from the production request path; they are installed only for explicit offline
jobs.
