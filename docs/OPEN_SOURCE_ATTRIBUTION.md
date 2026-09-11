# Open Source Attribution

| Dependency | Source | Version policy | License | Intended use |
|---|---|---|---|---|
| Haystack | `https://github.com/deepset-ai/haystack` | `>=3.1,<4` (optional) | Apache-2.0 | Internal indexing/retrieval adapters and later evaluated pipelines |

Haystack is open-source infrastructure, not MSB Radar business IP. The current
reference index is framework-independent and exists to test lifecycle and
security semantics before selecting a production document store.

Haystack 3 requires Python 3.10 or newer. Haystack 3.1.1 is installed in the
project-local Python 3.14 environment and the indexing adapter is integration
tested against its real in-memory document store. No production store has been
selected or claimed as verified.
