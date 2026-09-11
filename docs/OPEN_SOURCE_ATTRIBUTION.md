# Open Source Attribution

| Dependency | Source | Version policy | License | Intended use |
|---|---|---|---|---|
| Haystack | `https://github.com/deepset-ai/haystack` | `>=3.1,<4` (optional) | Apache-2.0 | Internal indexing/retrieval adapters and later evaluated pipelines |

Haystack is open-source infrastructure, not MSB Radar business IP. The current
reference index is framework-independent and exists to test lifecycle and
security semantics before selecting a production document store.

Haystack 3 requires Python 3.10 or newer. The current host only exposes Python
3.9, so the optional dependency is declared but its live adapter/install is not
claimed as verified on this host.
