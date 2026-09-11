# Radar Integration Contract Draft

This is a negotiation draft, not an implemented Radar endpoint.

## Request envelope

Every call includes `principal_id`, opaque `scope_token`, `request_id`, and a
scope fingerprint safe for cache partitioning. Intelligence treats missing or
empty scope as a hard error and never broadens scope.

## Document change event

Required fields: event ID, operation (`upsert`, `delete`, `person_reassigned`),
person ID, document ID, source record ID where applicable, version, content
hash, updated timestamp, document type/source, and authorized text locator.
Event ID plus operation must be idempotent. Delete wins over an older upsert.

## Evidence resolution

Evidence stores stable IDs, version/hash, an authorized source locator, and the
small retrieved passage. Before returning a citation, code checks that the
document still exists, is visible in the request scope, and matches the indexed
version/hash. Radar decides whether contact details or raw CV files may be shown.

Legacy inspection confirms the existing Talent document-text endpoint does not
return enough provenance for this check. The proposed resolver endpoint and its
service/scope headers are specified in `MIGRATION_PLAN.md`; an HTTP client with
fail-closed contract tests now exists in Intelligence.

## Action proposal

P1 tools return a proposal with arguments, evidence and risk. Consequential
actions remain `proposed` until Radar records an authenticated human approval;
Radar revalidates DNC, permissions, quota and current workflow state at execute
time.
