# -*- coding: utf-8 -*-
"""API People Intelligence — soi fact/provenance, hàng chờ review, coverage.

Xem raw / canonical / evidence của mọi giá trị (Master Plan §5, §21.6). Review &
alias governance chỉ admin (§21.2).
"""
from django.db.models import Count
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import RequiresAdmin, RequiresTalent
from people.models import ContactMention

from .extraction import coverage_summary
from .facts import accept_fact, reject_fact
from .models import (CanonicalAlias, CanonicalEntry, ExtractedFact, ExtractionRun,
                     ReviewItem)


def _fact_dict(fact):
    return {
        "id": fact.pk, "field": fact.field, "status": fact.status,
        "raw_value": fact.raw_value, "normalized_value": fact.normalized_value,
        "canonical_code": fact.canonical_code, "canonical_label": fact.canonical_label,
        "confidence": round(fact.confidence, 3),
        "source_kind": fact.source_kind,
        "source_record_id": fact.source_record_id, "document_id": fact.document_id,
        "evidence": fact.evidence, "extractor": fact.extractor, "model": fact.model,
        "schema_version": fact.schema_version,
        "observed_at": fact.observed_at, "valid_from": fact.valid_from,
        "valid_to": fact.valid_to, "is_current": fact.is_current,
    }


@api_view(["GET"])
@permission_classes([RequiresTalent])
def person_facts(request, person_id):
    facts = (ExtractedFact.objects.filter(person_id=person_id)
             .select_related("source_record", "document")
             .order_by("field", "-observed_at"))
    status_filter = request.query_params.get("status")
    if status_filter:
        facts = facts.filter(status=status_filter)
    by_field = {}
    for fact in facts:
        by_field.setdefault(fact.field, []).append(_fact_dict(fact))
    return Response({
        "person_id": int(person_id),
        "fields": by_field,
        "current": {f.field: _fact_dict(f) for f in facts if f.is_current
                    and f.status == ExtractedFact.STATUS_ACCEPTED},
    })


@api_view(["GET"])
@permission_classes([RequiresTalent])
def person_runs(request, person_id):
    runs = ExtractionRun.objects.filter(person_id=person_id).order_by("-started_at")[:20]
    return Response({"results": [{
        "id": r.pk, "status": r.status, "extractor": r.extractor,
        "provider": r.provider, "model": r.model, "dry_run": r.dry_run,
        "coverage": r.coverage, "error": r.error,
        "started_at": r.started_at, "finished_at": r.finished_at,
    } for r in runs]})


@api_view(["GET"])
@permission_classes([RequiresAdmin])
def review_queue(request):
    items = (ReviewItem.objects.filter(status=ReviewItem.STATUS_OPEN)
             .select_related("fact", "alias", "alias__namespace").order_by("-created_at"))
    reason = request.query_params.get("reason")
    if reason:
        items = items.filter(reason=reason)
    return Response({
        "counts": dict(ReviewItem.objects.filter(status=ReviewItem.STATUS_OPEN)
                       .values_list("reason").annotate(n=Count("id"))),
        "results": [{
            "id": it.pk, "reason": it.reason, "detail": it.detail,
            "person_id": it.person_id, "field": it.field,
            "fact": _fact_dict(it.fact) if it.fact_id else None,
            "alias": ({"id": it.alias_id, "namespace": it.alias.namespace.key,
                       "alias_norm": it.alias.alias_norm} if it.alias_id else None),
            "created_at": it.created_at,
        } for it in items[:200]],
    })


def _mention_dict(m):
    return {
        "id": m.pk, "subject_person_id": m.subject_id, "document_id": m.document_id,
        "full_name": m.full_name, "title": m.title, "company": m.company,
        "relationship_note": m.relationship_note,
        "email": m.email, "phone": m.phone, "kind": m.kind,
        "confidence": round(m.confidence, 3), "evidence": m.evidence,
        "extractor": m.extractor, "status": m.status,
        "linked_person_id": m.linked_person_id, "created_at": m.created_at,
    }


@api_view(["GET"])
@permission_classes([RequiresAdmin])
def contact_mention_queue(request):
    """Người tham chiếu/liên hệ bóc từ CV, chờ người xem xác nhận.

    Trước đây chỉ xem được trong trang quản trị Django — không có API nên React
    không dựng được hàng đợi. `extractor` phân biệt nguồn: `radar_contacts` (AI
    đọc mục tham chiếu trong text CV, có bằng chứng) vs `edge_blob` (vớt từ ô
    liên hệ gộp, chưa biết của ai, điểm tin thấp).
    """
    items = (ContactMention.objects.filter(status=ContactMention.STATUS_PROPOSED)
             .select_related("document").order_by("-confidence", "-created_at"))
    extractor = request.query_params.get("extractor")
    if extractor:
        items = items.filter(extractor=extractor)
    return Response({
        "counts": dict(ContactMention.objects
                       .filter(status=ContactMention.STATUS_PROPOSED)
                       .values_list("extractor").annotate(n=Count("id"))),
        "results": [_mention_dict(m) for m in items[:200]],
    })


@api_view(["POST"])
@permission_classes([RequiresAdmin])
def contact_mention_resolve(request, mention_id):
    """`decision` = accept | reject. Accept → tạo Person + PersonLink + Signal RB."""
    mention = ContactMention.objects.filter(
        pk=mention_id, status=ContactMention.STATUS_PROPOSED).first()
    if mention is None:
        return Response({"detail": "Không thấy liên hệ chờ duyệt."}, status=404)
    decision = str(request.data.get("decision") or "").lower()
    by = str(request.user)[:150]

    if decision == "accept":
        from .contacts import promote
        person = promote(mention, created_by=by)
        return Response({"ok": True, "status": mention.status,
                         "linked_person_id": person.pk if person else None})
    if decision == "reject":
        mention.status = ContactMention.STATUS_REJECTED
        mention.save(update_fields=["status", "updated_at"])
        return Response({"ok": True, "status": mention.status})
    return Response({"detail": "decision phải là accept hoặc reject."}, status=400)


@api_view(["POST"])
@permission_classes([RequiresAdmin])
def review_resolve(request, item_id):
    item = ReviewItem.objects.filter(pk=item_id, status=ReviewItem.STATUS_OPEN).first()
    if item is None:
        return Response({"detail": "Không thấy mục chờ duyệt."}, status=404)
    decision = str(request.data.get("decision") or "").lower()
    by = str(request.user)[:150]

    if decision == "accept":
        if item.fact_id:
            accept_fact(item.fact, by=by)
        item.resolve(ReviewItem.STATUS_ACCEPTED, by=by)
    elif decision == "reject":
        if item.fact_id:
            reject_fact(item.fact, by=by)
        item.resolve(ReviewItem.STATUS_REJECTED, by=by)
    else:
        return Response({"detail": "decision phải là accept hoặc reject."}, status=400)
    return Response({"ok": True, "status": item.status})


@api_view(["GET"])
@permission_classes([RequiresAdmin])
def alias_queue(request):
    aliases = (CanonicalAlias.objects.filter(status=CanonicalAlias.STATUS_PROPOSED)
               .select_related("namespace").order_by("namespace__key", "alias_norm"))
    ns = request.query_params.get("namespace")
    if ns:
        aliases = aliases.filter(namespace__key=ns)
    return Response({"results": [{
        "id": a.pk, "namespace": a.namespace.key, "alias_norm": a.alias_norm,
        "alias_raw": a.alias_raw, "source": a.source, "created_by": a.created_by,
        "created_at": a.created_at,
    } for a in aliases[:300]]})


@api_view(["POST"])
@permission_classes([RequiresAdmin])
def alias_resolve(request, alias_id):
    alias = CanonicalAlias.objects.filter(
        pk=alias_id, status=CanonicalAlias.STATUS_PROPOSED).first()
    if alias is None:
        return Response({"detail": "Không thấy alias."}, status=404)
    decision = str(request.data.get("decision") or "").lower()
    by = str(request.user)[:150]

    if decision == "accept":
        entry = CanonicalEntry.objects.filter(
            namespace=alias.namespace, code=request.data.get("entry_code")).first()
        if entry is None:
            return Response({"detail": "entry_code không hợp lệ cho namespace này."}, status=400)
        alias.accept(entry, by=by, note=str(request.data.get("note") or ""))
        from talent.semantic_index import clear_registry_alias_cache
        clear_registry_alias_cache()
    elif decision == "reject":
        alias.reject(by=by, note=str(request.data.get("note") or ""))
    else:
        return Response({"detail": "decision phải là accept hoặc reject."}, status=400)
    return Response({"ok": True, "status": alias.status,
                     "entry_code": alias.entry.code if alias.entry_id else ""})


@api_view(["GET"])
@permission_classes([RequiresAdmin])
def runs_dashboard(request):
    """Số liệu vận hành cho backfill/coverage (Master Plan §15 GĐ6, §21.6)."""
    recent = list(ExtractionRun.objects.order_by("-started_at")[:500])
    by_status = dict(ExtractionRun.objects.values_list("status")
                     .annotate(n=Count("id")))
    return Response({
        "totals": {
            "runs": ExtractionRun.objects.count(),
            "by_status": by_status,
            "open_reviews": ReviewItem.objects.filter(status=ReviewItem.STATUS_OPEN).count(),
            "proposed_aliases": CanonicalAlias.objects.filter(
                status=CanonicalAlias.STATUS_PROPOSED).count(),
            "accepted_facts": ExtractedFact.objects.filter(
                status=ExtractedFact.STATUS_ACCEPTED).count(),
        },
        "coverage_last_500": coverage_summary(recent),
        "recent": [{
            "id": r.pk, "person_id": r.person_id, "status": r.status,
            "coverage": r.coverage, "started_at": r.started_at,
        } for r in recent[:50]],
    })
