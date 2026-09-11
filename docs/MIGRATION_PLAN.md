# Radar Integration and Migration Plan

The legacy checkout is `D:\Project\MSB_Radar` (the literal
`D:\Project\MSB\_Radar` path does not exist). It remains read-only until a
separate integration phase explicitly authorizes product changes.

## Observed legacy contract

Radar currently exposes `GET /api/v1/talent/documents/{document_id}/text/` under
`RequiresRecruiting`. It returns redacted/full text, parse state and text
versions depending on contact-unlock state. This is suitable for the product
source panel but insufficient for Intelligence evidence validation because it
does not return the document's `person_id`, the selected text version's
`text_hash`, or a canonical version identifier.

Legacy `Document` is unique by `(person, sha256)`. Its stable searchable text is
`primary_text_version.text` when present, otherwise `parsed_text`.
`ParsedTextVersion` is unique by `(person, text_hash)`. Therefore the
Intelligence content hash must represent the selected parsed text, not blindly
reuse the binary file SHA-256.

## Required Radar endpoint

Proposed service-to-service endpoint:

`GET /api/v1/intelligence/evidence/documents/{document_id}/`

Headers:

- `Authorization: Bearer <service credential>` authenticates Intelligence.
- `X-Radar-Scope-Token: <opaque authorized scope>` carries the end-user scope.

Successful response:

```json
{
  "document_id": "12",
  "person_id": "7",
  "version": "text:31",
  "content_hash": "<normalized parsed-text SHA-256>",
  "exists": true
}
```

Radar must validate the scope token, current user/module permissions and Person
visibility, and write the relevant `AccessLog`. A `403` and `404` are treated
identically by Intelligence; `410` means deleted. The endpoint should not
return CV text because Intelligence already has the cited passage and only
needs current authorization and provenance.

## Rollout order

1. Agree scope-token issuer, lifetime, audience and revocation behavior.
2. Add the Radar endpoint and product-side permission/audit tests in a separately
   authorized legacy integration change.
3. Verify the new HTTP resolver against an isolated Radar environment.
4. Add versioned document-feed upsert/delete/reassignment endpoints.
5. Reindex an authorized non-production snapshot and reconcile every chunk to
   Person/Document IDs.
6. Run lexical and semantic V1/V2 evaluation on the identical snapshot.
7. Only after evidence and retrieval gates pass, enable grounded Q&A behind a
   feature flag and canary it before any legacy Answer Engine routing changes.

No product endpoint, production data or legacy source was changed in this
phase.

## Required document feed

Proposed endpoint:

`GET /api/v1/intelligence/document-feed/?cursor=<opaque>&limit=<1..1000>`

It uses the same service authentication and a dedicated index scope token. The
response contains ordered events plus `next_cursor` and `has_more`. Every event
contains `event_id`, operation (`upsert`, `delete`, `person_reassigned`), Radar
Person/Document IDs, selected parsed-text version and hash, source provenance,
timestamp and text for non-delete operations.

The cursor represents a durable Radar-side sequence, not an `updated_at` scan;
timestamps alone can miss same-time writes and cannot provide stable replay.
Intelligence commits the cursor only after all events in the page are applied.
Existing Edge `entity_key + content_hash` semantics inform idempotency, but the
Edge outbox is not reused as the Intelligence feed because it precedes final
Person resolution and selected parsed-text versioning.

The new repository includes a strict feed client and event mapper with mocked
contract tests. The product endpoint and durable change log remain pending.

The sync coordinator now enforces this checkpoint rule and reports pages,
events, status counts, chunk count, start/end cursor and whether it caught up.
If an event fails, that page's cursor is not saved. If checkpoint persistence
fails after indexing, replay is safe because event IDs are idempotent. A
non-empty page without a next cursor is rejected because it could never be
acknowledged safely.
