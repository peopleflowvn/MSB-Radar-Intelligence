"""Private, least-privilege bridge for the Intelligence V2 backend."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core import signing
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from people.models import Document
from accounts import roles

from .corpus_qa import can_read_cv
from .models import IntelligenceDocumentTombstone


_SCOPE_SALT = "radar-intelligence-scope-v1"
_MAX_PAGE_SIZE = 1000


def _secret_matches(request, header, expected):
    supplied = request.headers.get(header, "")
    return bool(expected) and hmac.compare_digest(supplied, expected)


def _service_authorized(request):
    value = request.headers.get("Authorization", "")
    prefix = "Bearer "
    supplied = value[len(prefix):] if value.startswith(prefix) else ""
    return bool(settings.INTELLIGENCE_SERVICE_TOKEN) and hmac.compare_digest(
        supplied, settings.INTELLIGENCE_SERVICE_TOKEN)


def _deny():
    # Do not reveal whether a private endpoint, document, or token exists.
    return JsonResponse({"detail": "Not found."}, status=404)


def _encode_cursor(updated_at, kind, pk):
    raw = json.dumps({"t": updated_at.isoformat(), "k": kind, "id": pk}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(value):
    try:
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
        stamp = datetime.fromisoformat(data["t"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt_timezone.utc)
        return stamp, int(data.get("k", 0)), int(data["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise ValueError("invalid cursor")


def _document_payload(document):
    text = document.best_text or ""
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    source_record = next(iter(document.source_records.all()), None)
    event_identity = ":".join((
        str(document.pk),
        str(document.person_id),
        document.updated_at.isoformat(),
        content_hash,
    ))
    event_id = hashlib.sha256(event_identity.encode("utf-8")).hexdigest()
    return {
        # Event identity covers ownership and revision time as well as text.
        # This prevents a metadata/reassignment update with unchanged text from
        # reusing an earlier event id with a different payload.
        "event_id": f"document:{document.pk}:{event_id}",
        "operation": "upsert",
        "document_id": str(document.pk),
        "person_id": str(document.person_id),
        "version": content_hash,
        "content_hash": content_hash,
        "source_record_id": str(source_record.pk) if source_record else None,
        "source": document.source or (source_record.source if source_record else "") or "radar",
        "document_type": document.document_type,
        "text": text,
        "updated_at": document.updated_at.isoformat(),
        "document_date": document.observed_at.isoformat() if document.observed_at else None,
        "application_id": str(source_record.pk) if source_record else None,
    }


def _tombstone_payload(tombstone):
    return {
        "event_id": f"document-delete:{tombstone.pk}",
        "operation": "delete",
        "document_id": str(tombstone.document_id),
        "person_id": str(tombstone.person_id),
        "version": tombstone.version,
        "content_hash": tombstone.content_hash,
        "source_record_id": None,
        "source": tombstone.source,
        "document_type": tombstone.document_type,
        "text": None,
        "updated_at": tombstone.deleted_at.isoformat(),
        "document_date": None,
        "application_id": None,
    }


def issue_scope_token(user):
    return signing.dumps({"user_id": user.pk, "purpose": "talent_cv"}, salt=_SCOPE_SALT,
                         compress=True)


def _scope_user(scope_token):
    try:
        payload = signing.loads(
            scope_token, salt=_SCOPE_SALT,
            max_age=settings.INTELLIGENCE_SCOPE_MAX_AGE_SECONDS)
        if payload.get("purpose") != "talent_cv":
            return None
        from django.contrib.auth import get_user_model
        return get_user_model().objects.filter(pk=payload.get("user_id"), is_active=True).first()
    except (signing.BadSignature, signing.SignatureExpired, TypeError):
        return None


@require_POST
def intelligence_scope(request):
    if (not request.user.is_authenticated
            or not roles.can_access(request.user, roles.MODULE_TALENT)
            or not can_read_cv(request.user)):
        return _deny()
    return JsonResponse({
        "scope_token": issue_scope_token(request.user),
        "expires_in": settings.INTELLIGENCE_SCOPE_MAX_AGE_SECONDS,
    })


@csrf_exempt
@require_POST
def validate_scope(request):
    if not _service_authorized(request):
        return _deny()
    user = _scope_user(request.headers.get("X-Radar-Scope-Token", ""))
    if (user is None or not roles.can_access(user, roles.MODULE_TALENT)
            or not can_read_cv(user)):
        return _deny()
    # Record-level Talent visibility is currently corpus-wide. Keep this claim
    # explicit so a future row policy can replace it without trusting V2.
    return JsonResponse({"allowed": True, "scope": "all_applicants"})


@require_GET
def document_feed(request):
    if not _service_authorized(request) or not _secret_matches(
            request, "X-Radar-Scope-Token", settings.INTELLIGENCE_INDEX_SCOPE_TOKEN):
        return _deny()
    try:
        limit = int(request.GET.get("limit", "100"))
        if not 1 <= limit <= _MAX_PAGE_SIZE:
            raise ValueError
    except ValueError:
        return JsonResponse({"detail": "Invalid limit."}, status=400)

    from django.db.models import Q
    documents = (Document.objects.filter(
        person__merged_into__isnull=True, person__is_applicant=True,
        parse_status=Document.PARSE_DONE)
        .filter(Q(primary_text_version__text__gt="")
                | Q(primary_text_version__isnull=True, parsed_text__gt=""))
        .select_related("primary_text_version")
        .prefetch_related("source_records")
        .order_by("updated_at", "pk"))
    tombstones = IntelligenceDocumentTombstone.objects.order_by("deleted_at", "pk")
    cursor = request.GET.get("cursor")
    if cursor:
        try:
            stamp, kind, pk = _decode_cursor(cursor)
        except ValueError:
            return JsonResponse({"detail": "Invalid cursor."}, status=400)
        documents = documents.filter(
            Q(updated_at__gt=stamp)
            | (Q(updated_at=stamp, pk__gt=pk) if kind == 0 else Q(pk__isnull=True)))
        tombstones = tombstones.filter(
            Q(deleted_at__gt=stamp)
            | Q(deleted_at=stamp, pk__gt=pk)
            | (Q(deleted_at=stamp) if kind == 0 else Q(pk__isnull=True)))

    rows = ([(row.updated_at, 0, row.pk, row) for row in documents[:limit + 1]]
            + [(row.deleted_at, 1, row.pk, row) for row in tombstones[:limit + 1]])
    rows.sort(key=lambda row: row[:3])
    rows = rows[:limit + 1]
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode_cursor(*rows[-1][:3]) if rows else cursor
    return JsonResponse({
        "events": [(_document_payload(row) if kind == 0 else _tombstone_payload(row))
                   for _, kind, _, row in rows],
        "next_cursor": next_cursor,
        "has_more": has_more,
    })


@require_GET
def evidence_document(request, document_id):
    if not _service_authorized(request):
        return _deny()
    user = _scope_user(request.headers.get("X-Radar-Scope-Token", ""))
    if (user is None or not roles.can_access(user, roles.MODULE_TALENT)
            or not can_read_cv(user)):
        return _deny()
    document = (Document.objects.select_related("person", "primary_text_version")
                .filter(pk=document_id, person__merged_into__isnull=True,
                        person__is_applicant=True).first())
    if document is None:
        return _deny()
    payload = _document_payload(document)
    return JsonResponse({key: payload[key] for key in (
        "document_id", "person_id", "version", "content_hash")})
