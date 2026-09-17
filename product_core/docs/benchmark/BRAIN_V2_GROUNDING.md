# Brain V2 — citation assignment and grounding audit

Date: 2026-09-08. Scope: deterministic source assignment in local code and
synthetic fixtures. Semantic entailment and production hallucination rate are
NOT MEASURED.

The previous final-answer verifier established that a cited source number existed
and belonged to every person mentioned somewhere in the answer. It did not bind a
source to the nearby person claim. Two counterexamples failed before this change:

- `An ... [2]. Bình ... [1].` passed when source 1 belonged to An and source 2
  belonged to Bình, because both owners appeared somewhere in the global set;
- the short name `An` was detected inside the unrelated word `Ngân`.

The verifier now matches complete Unicode word boundaries and inspects every name
occurrence. A person passes when at least one of their occurrences is followed,
before the next person mention, by a source owned by that same person. Repeated
introductory names remain valid when the later detailed block has the right source.
An invalid number or missing local source triggers the existing single repair
attempt and deterministic fallback if the repaired answer still fails.

Every non-chat Talent answer now exposes `trace.citation_audit` with:

- `status`, `mentioned_people`, and `locally_cited_people`;
- `invalid_source_numbers` and `missing_local_source`;
- `semantic_entailment: NOT_MEASURED`.

The live `answer_eval` command includes the same ownership check as
`citations_owned`, so a report cannot pass only because all cited IDs exist.

## Verification

- Before: 10 verifier tests, 2 failures matching the counterexamples above.
- After: 23 verifier/Answer Engine tests pass in 6.313 seconds.
- Final affected regression: 802 AI/Talent/Intel/People tests pass in 121.517
  seconds. Missing or failed logs must remain NOT MEASURED.

This audit proves source-number existence, local assignment, and profile ownership.
It does not prove that the quoted words logically entail a model judgement, that a
CV statement is true, or that omitted/negative evidence is complete. Those require
versioned production evidence spans and independent recruiter review. The local
rule deliberately prefers explicit per-person citations; prose that groups several
people under one trailing citation group may be rewritten into separate sourced
claims.

Rollback the verifier, trace field, evaluation check, and tests together. No schema
migration, production write, route change, push, or deployment is part of this work.
