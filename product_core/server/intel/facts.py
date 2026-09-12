# -*- coding: utf-8 -*-
"""Ghi và hợp nhất `ExtractedFact` (Master Plan §5, §2.3, §21.1).

`record_fact()` idempotent theo fingerprint. Sau mỗi lần ghi, `_recompute_current()`
đặt lại `is_current` cho (person, field) theo quy tắc ở `field_rules`:

* `latest` — fact accepted có `observed_at` mới nhất là hiện hành; cũ hơn thì
  `is_current=False`, `valid_to` = observed_at của bản kế tiếp.
* `merge`  — mọi fact accepted đều hiện hành.

Con người thắng máy: nếu có fact `source_kind=manual` (curated) cho field thì AI/
Edge **không** được auto-accept đè lên — chỉ vào review.
"""
import hashlib

from django.db import IntegrityError
from django.utils import timezone

from .field_rules import rule_for
from .models import ExtractedFact, ReviewItem
from .registry import resolve

CURATED_KIND = ExtractedFact.SOURCE_MANUAL


def _fingerprint(person_id, field, source_kind, source_record_id, document_id,
                 schema_version, value_key):
    raw = "|".join(str(x) for x in (
        person_id, field, source_kind, source_record_id or "", document_id or "",
        schema_version, value_key))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def has_curated(person_id, field):
    return ExtractedFact.objects.filter(
        person_id=person_id, field=field, source_kind=CURATED_KIND,
        status=ExtractedFact.STATUS_ACCEPTED).exists()


def record_fact(person, field, raw_value, *, source_kind, run=None, confidence=1.0,
                evidence="", source_record=None, document=None, extractor="",
                model="", schema_version=1, observed_at=None, valid_from=None,
                created_by=""):
    """Ghi một fact. Trả `(fact, created)`. Idempotent theo fingerprint."""
    person_id = getattr(person, "pk", person)
    rule = rule_for(field)
    observed_at = observed_at or timezone.now()

    normalized = str(raw_value or "").strip()
    canonical_code = canonical_label = ""
    review_reason = ""
    if rule["namespace"]:
        res = resolve(rule["namespace"], raw_value,
                      source=extractor or "radar_ai", created_by=created_by)
        normalized = res.normalized or normalized
        if res.entry is not None:
            canonical_code, canonical_label = res.code, res.label
        elif res.created_candidate:
            review_reason = ReviewItem.REASON_ALIAS

    value_key = canonical_code or normalized or str(raw_value or "").strip().casefold()
    fp = _fingerprint(person_id, field, source_kind,
                      getattr(source_record, "pk", None), getattr(document, "pk", None),
                      schema_version, value_key)

    defaults = {
        "person_id": person_id, "run": run, "field": field,
        "raw_value": str(raw_value or "")[:500], "normalized_value": normalized[:500],
        "canonical_code": canonical_code, "canonical_label": canonical_label,
        "confidence": float(confidence), "source_kind": source_kind,
        "source_record": source_record, "document": document,
        "evidence": str(evidence or "")[:4000], "extractor": extractor[:40],
        "model": model[:120], "schema_version": schema_version,
        "observed_at": observed_at, "valid_from": valid_from or observed_at,
    }
    try:
        fact, created = ExtractedFact.objects.get_or_create(
            fingerprint=fp, defaults=defaults)
    except IntegrityError:
        fact, created = ExtractedFact.objects.get(fingerprint=fp), False

    if not created:
        # Chạy lại an toàn: cập nhật evidence/confidence/run nếu prompt/model đổi.
        touched = ["confidence", "evidence", "run", "updated_at"]
        fact.confidence = float(confidence)
        fact.evidence = str(evidence or "")[:4000] or fact.evidence
        if run is not None:
            fact.run = run
        # Alias có thể đã được duyệt sau lần chạy trước — nạp lại mã chuẩn.
        if canonical_code and not fact.canonical_code:
            fact.canonical_code = canonical_code
            fact.canonical_label = canonical_label
            touched += ["canonical_code", "canonical_label"]
        fact.save(update_fields=touched)
        if "canonical_code" in touched:
            _recompute_current(person_id, field)
        return fact, False

    # --- quyết định status ---
    trusted_source = source_kind in (ExtractedFact.SOURCE_EDGE,
                                     ExtractedFact.SOURCE_PROFILE, CURATED_KIND)
    curated = has_curated(person_id, field) and source_kind != CURATED_KIND
    if source_kind == CURATED_KIND:
        fact.status = ExtractedFact.STATUS_ACCEPTED
    elif curated:
        fact.status = ExtractedFact.STATUS_CONFLICT
        _open_review(fact, ReviewItem.REASON_CONFLICT, "Đã có giá trị người dùng sửa tay")
    elif rule["sensitive"] and not trusted_source:
        fact.status = ExtractedFact.STATUS_PROPOSED
        _open_review(fact, ReviewItem.REASON_SENSITIVE, f"Trường nhạy cảm: {field}")
    elif trusted_source:
        # Giá trị Edge/hồ sơ đáng tin (§2.3): fact được nhận; alias chưa nhận diện
        # thì để candidate trong hàng chờ, KHÔNG chặn fact.
        fact.status = ExtractedFact.STATUS_ACCEPTED
    elif review_reason:
        fact.status = ExtractedFact.STATUS_PROPOSED
        _open_review(fact, review_reason, f"Alias chưa nhận diện: {fact.raw_value}")
    elif rule["auto_accept"] and confidence >= rule["gate"]:
        fact.status = ExtractedFact.STATUS_ACCEPTED
    else:
        fact.status = ExtractedFact.STATUS_PROPOSED
        _open_review(fact, ReviewItem.REASON_LOW_CONFIDENCE,
                     f"confidence {confidence:.2f} < {rule['gate']:.2f}")
    fact.save(update_fields=["status", "updated_at"])

    _recompute_current(person_id, field)
    return fact, True


def _open_review(fact, reason, detail):
    ReviewItem.objects.get_or_create(
        fact=fact, reason=reason,
        defaults={"person_id": fact.person_id, "field": fact.field, "detail": detail[:300]})


def _recompute_current(person_id, field):
    rule = rule_for(field)
    accepted = list(ExtractedFact.objects
                    .filter(person_id=person_id, field=field,
                            status=ExtractedFact.STATUS_ACCEPTED)
                    .order_by("-observed_at", "-pk"))
    if not accepted:
        return

    if rule["mode"] == "merge":
        ids = [f.pk for f in accepted]
        ExtractedFact.objects.filter(pk__in=ids).update(is_current=True, valid_to=None)
        return

    # latest: xếp theo (độ tin nguồn, độ mới). manual > edge > profile > cv_text > ai;
    # trong cùng mức nguồn thì evidence mới nhất thắng (§7.3).
    trust = {ExtractedFact.SOURCE_MANUAL: 0, ExtractedFact.SOURCE_EDGE: 1,
             ExtractedFact.SOURCE_PROFILE: 2, ExtractedFact.SOURCE_CV_TEXT: 3,
             ExtractedFact.SOURCE_AI: 4}
    ranked = sorted(accepted, key=lambda f: (
        trust.get(f.source_kind, 5), -(f.observed_at.timestamp() if f.observed_at else 0)))
    winner = ranked[0]
    ExtractedFact.objects.filter(pk=winner.pk).update(is_current=True, valid_to=None)
    losers = [f for f in accepted if f.pk != winner.pk]
    if losers:
        ExtractedFact.objects.filter(pk__in=[f.pk for f in losers]).update(
            is_current=False, valid_to=winner.observed_at)


def current_facts(person, field=None):
    qs = ExtractedFact.objects.filter(
        person_id=getattr(person, "pk", person),
        status=ExtractedFact.STATUS_ACCEPTED, is_current=True)
    if field:
        qs = qs.filter(field=field)
    return qs.order_by("field", "-observed_at")


def accept_fact(fact, *, by=""):
    """Người duyệt chấp nhận một fact proposed."""
    fact.status = ExtractedFact.STATUS_ACCEPTED
    fact.save(update_fields=["status", "updated_at"])
    fact.review_items.filter(status=ReviewItem.STATUS_OPEN).update(
        status=ReviewItem.STATUS_ACCEPTED, resolved_by=str(by)[:150],
        resolved_at=timezone.now())
    _recompute_current(fact.person_id, fact.field)
    return fact


def reject_fact(fact, *, by=""):
    fact.status = ExtractedFact.STATUS_REJECTED
    fact.is_current = False
    fact.save(update_fields=["status", "is_current", "updated_at"])
    fact.review_items.filter(status=ReviewItem.STATUS_OPEN).update(
        status=ReviewItem.STATUS_REJECTED, resolved_by=str(by)[:150],
        resolved_at=timezone.now())
    _recompute_current(fact.person_id, fact.field)
    return fact
