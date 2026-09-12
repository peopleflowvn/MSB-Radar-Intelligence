# -*- coding: utf-8 -*-
"""Materialized search projection (Master Plan §21.7).

Chỉ fact `accepted` mới vào `MaterializedProfile`. Có version và lệnh rebuild/audit;
reader tìm kiếm hiện tại chưa được chuyển sang ảnh này.
"""
import hashlib
import json

from django.utils import timezone

from people.models import Person

from .facts import current_facts
from .field_rules import MERGE_FIELDS
from .models import ExtractedFact, ExtractionRun, MaterializedProfile

PROJECTION_VERSION = 2


def _fact_state(fact):
    state = {field: getattr(fact, field) for field in (
        "field", "raw_value", "normalized_value", "canonical_code", "canonical_label",
        "confidence", "status", "is_current", "schema_version", "evidence",
        "updated_at", "document_id", "source_record_id")}
    state["document_version"] = ((fact.document.sha256, fact.document.updated_at)
                                 if fact.document_id else None)
    state["record_version"] = ((fact.source_record.content_hash, fact.source_record.revision)
                               if fact.source_record_id else None)
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()

# field → namespace của mã canonical, để gom `codes` cho bộ lọc nhanh.
_CODE_FIELDS = {
    "city": "location", "location_interest": "location",
    "skills": "skill", "industries": "industry",
    "current_title": "job_title", "applied_position": "job_title",
    "seniority": "seniority", "education_level": "education_level",
}


def build_for_person(person):
    person_id = getattr(person, "pk", person)
    facts = list(current_facts(person_id).select_related(
        "run", "document", "source_record"))

    data = {}
    codes = {}
    for fact in facts:
        entry = {
            "fact_id": fact.pk,
            "fact_state_sha256": _fact_state(fact),
            "value": fact.canonical_label or fact.normalized_value or fact.raw_value,
            "code": fact.canonical_code,
            "confidence": round(fact.confidence, 3),
            "status": fact.status,
            "schema_version": fact.schema_version,
            "extractor": fact.extractor,
            "model": fact.model,
            "source_kind": fact.source_kind,
            "observed_at": fact.observed_at.isoformat() if fact.observed_at else None,
            "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
            "valid_to": fact.valid_to.isoformat() if fact.valid_to else None,
            "fact_fingerprint": fact.fingerprint,
            "source": {
                "run_id": fact.run_id,
                "document_id": fact.document_id,
                "document_sha256": fact.document.sha256 if fact.document_id else "",
                "document_updated_at": (
                    fact.document.updated_at.isoformat() if fact.document_id else None),
                "source_record_id": fact.source_record_id,
                "source_record_hash": (
                    fact.source_record.content_hash if fact.source_record_id else ""),
                "source_record_revision": (
                    fact.source_record.revision if fact.source_record_id else None),
            },
            "evidence": fact.evidence[:300],
        }
        if fact.field in MERGE_FIELDS:
            data.setdefault(fact.field, []).append(entry)
        else:
            data[fact.field] = entry
        bucket = _CODE_FIELDS.get(fact.field)
        if bucket and fact.canonical_code:
            codes.setdefault(bucket, [])
            if fact.canonical_code not in codes[bucket]:
                codes[bucket].append(fact.canonical_code)

    proj, _ = MaterializedProfile.objects.update_or_create(
        person_id=person_id,
        defaults={"projection_version": PROJECTION_VERSION, "data": data,
                  "codes": codes, "fact_count": len(facts),
                  "built_at": timezone.now()})
    return proj


def rebuild_all(*, limit=None, on_progress=None):
    # Build an explicit empty projection too. Without it, "no accepted fact"
    # is indistinguishable from "projection never built", so coverage cannot
    # support audited structured reads or counts.
    qs = Person.applicants().order_by("pk").values_list("pk", flat=True)
    if limit:
        qs = qs[:limit]
    stats = {"built": 0}
    for position, pid in enumerate(qs.iterator(), 1):
        build_for_person(pid)
        stats["built"] += 1
        if on_progress and position % 100 == 0:
            on_progress(position)
    return stats


def _entries(data):
    for value in (data or {}).values():
        if isinstance(value, list):
            yield from (entry for entry in value if isinstance(entry, dict))
        elif isinstance(value, dict):
            yield value


def audit():
    """Read-only projection integrity/coverage report; never rebuild implicitly."""
    population = set(Person.applicants().values_list("id", flat=True))
    extracted = set(ExtractionRun.objects.filter(
        person_id__in=population, status=ExtractionRun.STATUS_DONE,
        dry_run=False).values_list("person_id", flat=True))
    fact_rows = list(ExtractedFact.objects.filter(
        status=ExtractedFact.STATUS_ACCEPTED, is_current=True,
        person_id__in=population).select_related("document", "source_record"))
    state_by_fact = {fact.pk: _fact_state(fact) for fact in fact_rows}
    expected_by_person = {person_id: set() for person_id in population}
    field_people = {}
    for fact in fact_rows:
        fact_id, person_id, field = fact.pk, fact.person_id, fact.field
        expected_by_person[person_id].add(fact_id)
        field_people.setdefault(field, set()).add(person_id)
    profiles = list(MaterializedProfile.objects.filter(
        person_id__in=population).select_related("person"))
    rows = []
    for profile in profiles:
        entries = list(_entries(profile.data))
        fact_ids = {entry.get("fact_id") for entry in entries if entry.get("fact_id")}
        expected = expected_by_person.get(profile.person_id, set())
        provenance_complete = all(
            entry.get("fact_id") and entry.get("status") == ExtractedFact.STATUS_ACCEPTED
            and type(entry.get("schema_version")) is int
            and isinstance(entry.get("source"), dict)
            and entry.get("fact_state_sha256") == state_by_fact.get(entry.get("fact_id"))
            for entry in entries)
        rows.append({"person_id": profile.person_id,
                     "extraction_covered": profile.person_id in extracted,
                     "projection_version": profile.projection_version,
                     "version_current": profile.projection_version == PROJECTION_VERSION,
                     "fact_ids_match": fact_ids == expected,
                     "fact_count_match": profile.fact_count == len(expected),
                     "provenance_complete": provenance_complete})
    covered = {profile.person_id for profile in profiles}
    denominator = len(population)
    integrity_ready = covered == population and all(
        row["version_current"] and row["fact_ids_match"]
        and row["fact_count_match"] and row["provenance_complete"] for row in rows)
    return {
        "projection_version": PROJECTION_VERSION,
        "applicant_people": denominator, "profiles": len(profiles),
        "extraction_covered_people": len(extracted),
        "extraction_coverage_rate": len(extracted) / denominator if denominator else None,
        "missing_profiles": len(population - covered),
        "stale_profiles": sum(not row["version_current"] for row in rows),
        "invalid_profiles": sum(not (row["fact_ids_match"]
                                      and row["fact_count_match"]
                                      and row["provenance_complete"]) for row in rows),
        "field_coverage": {field: {"people": len(ids), "total": denominator,
                                     "rate": len(ids) / denominator if denominator else None}
                           for field, ids in sorted(field_people.items())},
        "integrity_ready": integrity_ready,
        "ready": integrity_ready and extracted == population,
        "rows": rows,
    }
