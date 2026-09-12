# -*- coding: utf-8 -*-
"""Báo cáo chỉ-đếm cho chuỗi Edge/intake -> Talent search trên môi trường thật."""
import json

from django.core.management.base import BaseCommand
from django.db.models import Count, F, Q
from django.utils import timezone

from core.models import Edge, SourceRecord
from intake.models import ImportBatch, ImportRow
from intel.models import ExtractedFact, ExtractionJob, ExtractionRun
from people.models import Document, DocumentTextLink, Person
from talent.models import CVChunk, EmbeddingConfig, PersonSearchDocument, TalentProfile
from ai.models import LLMCall, ProviderConfig, TaskModelRoute
from intel.edge_mapper import PAYLOAD_KEYS as EDGE_FACT_KEYS
from talent.derive import SIMPLE_FIELDS as PROFILE_PAYLOAD_KEYS


def _grouped(queryset, *fields):
    return list(queryset.values(*fields).annotate(count=Count("id")).order_by(*fields))


def collect_pipeline_audit():
    """Trả số liệu tổng hợp, không chứa tên hoặc thông tin liên hệ ứng viên."""
    profiles = TalentProfile.objects.all()
    profile_total = profiles.count()
    coverage = {}
    for field in (
        "current_title", "current_company", "education", "location",
        "desired_location", "seniority", "desired_level", "desired_position",
        "job_type", "foreign_language", "years_experience", "skills", "industries",
    ):
        model_field = TalentProfile._meta.get_field(field)
        field_type = model_field.get_internal_type()
        if field_type == "JSONField":
            filled = profiles.exclude(**{field: []}).exclude(
                **{f"{field}__isnull": True}).count()
        elif field_type in {"FloatField", "DecimalField", "IntegerField"}:
            filled = profiles.exclude(**{f"{field}__isnull": True}).count()
        else:
            filled = profiles.exclude(**{field: ""}).exclude(
                **{f"{field}__isnull": True}).count()
        coverage[field] = {"filled": filled, "total": profile_total}

    now = timezone.now()
    edges = []
    for edge in Edge.objects.all().order_by("edge_id"):
        edges.append({
            "edge_id": edge.edge_id,
            "active": edge.is_active,
            "last_seen_at": edge.last_seen_at,
            "age_minutes": round((now - edge.last_seen_at).total_seconds() / 60, 1)
            if edge.last_seen_at else None,
            "source_records": edge.source_records.count(),
            "resolved": edge.source_records.filter(
                status=SourceRecord.STATUS_RESOLVED).count(),
            "pending": edge.source_records.filter(
                status=SourceRecord.STATUS_PENDING).count(),
            "data_reported_at": edge.data_reported_at,
            "edge_report": edge.data_report,
            "candidate_gap": ((edge.data_report.get("candidates", {}).get("total", 0)
                               - edge.source_records.count())
                              if edge.data_report else None),
        })

    documents = Document.objects.all()
    with_text = documents.filter(
        Q(primary_text_version__isnull=False) | ~Q(parsed_text="")).distinct()
    manual_edge = Edge.objects.filter(edge_id="hub-manual").first()
    manual_records = (SourceRecord.objects.filter(edge=manual_edge)
                      if manual_edge else SourceRecord.objects.none())
    embedding_cfg = EmbeddingConfig.objects.filter(pk=1).first()
    effective = embedding_cfg.resolve() if embedding_cfg else None
    embedding_route = TaskModelRoute.objects.filter(task="talent_embedding").first()
    provider_state = {}
    for name in ("greennode", "gemini"):
        pc = ProviderConfig.objects.filter(provider=name).first()
        provider_state[name] = {
            "configured": bool(pc), "enabled": bool(pc and pc.enabled),
            "key_present": bool(pc and pc.get_api_key()),
        }
    payload_coverage = {}
    raw_source_payload = extensions = 0
    for payload in SourceRecord.objects.values_list("payload", flat=True).iterator(
            chunk_size=500):
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if value not in (None, "", [], {}):
                payload_coverage[key] = payload_coverage.get(key, 0) + 1
        raw_source_payload += int(bool(payload.get("source_payload")))
        extensions += int(bool(payload.get("extensions")))
    structured_keys = set()
    for keys in EDGE_FACT_KEYS.values():
        structured_keys.update(keys)
    for keys in PROFILE_PAYLOAD_KEYS.values():
        structured_keys.update(keys)
    operational_or_provenance = {
        "entity_type", "entity_key", "edge_id", "source", "account", "cv_id",
        "candidate_id", "resume_id", "campaign_id", "first_seen", "cv_url",
        "attachment_name", "attachment_mime", "source_payload", "extensions",
    }
    raw_only_keys = sorted(set(payload_coverage) - structured_keys - operational_or_provenance)

    return {
        "generated_at": now,
        "edges": edges,
        "source_records": {
            "total": SourceRecord.objects.count(),
            "by_edge_source": _grouped(
                SourceRecord.objects.all(), "edge__edge_id", "source"),
            "by_status": _grouped(SourceRecord.objects.all(), "status"),
            "without_person": SourceRecord.objects.filter(person__isnull=True).count(),
            "never_attempted": SourceRecord.objects.filter(
                status=SourceRecord.STATUS_PENDING,
                resolve_attempted_at__isnull=True).count(),
            "payload_nonempty_by_key": dict(sorted(payload_coverage.items())),
            "with_raw_source_payload": raw_source_payload,
            "with_versioned_extensions": extensions,
            "keys_with_structured_mapping": sorted(set(payload_coverage) & structured_keys),
            "keys_kept_for_recall_without_structured_mapping": raw_only_keys,
        },
        "people_search_projection": {
            "persons": Person.objects.filter(merged_into__isnull=True).count(),
            "talent_profiles": profile_total,
            "persons_from_source_without_profile": Person.objects.filter(
                merged_into__isnull=True, source_records__isnull=False,
                talent_profile__isnull=True).distinct().count(),
            "coverage": coverage,
        },
        "embedding": {
            "configured_mode": embedding_cfg.mode if embedding_cfg else None,
            "configured_model": ({
                "greennode": embedding_cfg.greennode_model,
                "gemini": embedding_cfg.gemini_model,
                "selfhost": embedding_cfg.selfhost_model,
            }.get(embedding_cfg.mode) if embedding_cfg else None),
            "effective": ({"provider": effective[0], "model": effective[3]}
                          if effective else None),
            "providers": provider_state,
            "task_route": ({"provider": embedding_route.provider,
                            "model": embedding_route.model,
                            "enabled": embedding_route.enabled}
                           if embedding_route else None),
            "projections": PersonSearchDocument.objects.count(),
            "projections_current": PersonSearchDocument.objects.filter(
                embedding_fingerprint=F("fingerprint")).count(),
            "projection_models": _grouped(
                PersonSearchDocument.objects.exclude(embedding_model=""), "embedding_model"),
            "chunks": CVChunk.objects.count(),
            "chunks_current": CVChunk.objects.filter(
                embedding_fingerprint=F("fingerprint")).count(),
            "chunk_models": _grouped(CVChunk.objects.exclude(embedding_model=""),
                                     "embedding_model"),
            "calls": _grouped(LLMCall.objects.filter(task="talent_embedding"),
                              "provider", "model", "ok"),
        },
        "documents": {
            "total": documents.count(),
            "with_file": documents.exclude(storage_key="").count(),
            "without_file": documents.filter(storage_key="").count(),
            "with_text": with_text.count(),
            "without_text": documents.exclude(storage_key="").filter(
                primary_text_version__isnull=True, parsed_text="").count(),
            "by_parse_status": _grouped(documents, "parse_status"),
            "by_source": _grouped(documents, "source"),
            "text_origins": _grouped(DocumentTextLink.objects.all(), "origins"),
        },
        "ai_extraction": {
            "jobs_by_status": _grouped(ExtractionJob.objects.all(), "status"),
            "runs_by_status": _grouped(ExtractionRun.objects.all(), "status"),
            "facts_total": ExtractedFact.objects.count(),
            "facts_ai": ExtractedFact.objects.filter(source_kind="ai").count(),
            "ai_facts_by_status": _grouped(
                ExtractedFact.objects.filter(source_kind="ai"), "status"),
            "ai_facts_by_field": _grouped(
                ExtractedFact.objects.filter(source_kind="ai"), "field"),
        },
        "manual_intake": {
            "batches": ImportBatch.objects.count(),
            "batches_by_kind_status": _grouped(
                ImportBatch.objects.all(), "kind", "status"),
            "rows": ImportRow.objects.count(),
            "rows_by_status": _grouped(ImportRow.objects.all(), "validation_status"),
            "rows_ai_extracted": ImportRow.objects.filter(ai_extracted=True).count(),
            "rows_committed_without_source_record": ImportRow.objects.filter(
                validation_status=ImportRow.STATUS_COMMITTED,
                source_record__isnull=True).count(),
            "manual_source_records": manual_records.count(),
            "manual_resolved": manual_records.filter(
                status=SourceRecord.STATUS_RESOLVED).count(),
            "manual_pending": manual_records.filter(
                status=SourceRecord.STATUS_PENDING).count(),
            "manual_documents": documents.filter(
                source_records__edge=manual_edge).distinct().count() if manual_edge else 0,
        },
    }


class Command(BaseCommand):
    help = "In báo cáo JSON kiểm toán nguồn dữ liệu phục vụ Talent search."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(
            collect_pipeline_audit(), ensure_ascii=True, default=str,
            separators=(",", ":")))
