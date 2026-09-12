# -*- coding: utf-8 -*-
"""Long-term memory + feedback + session-history search (Master Plan §11.2, §11.3, §15 GĐ5).

Hai store memory tách biệt (`scope`): `profile` và `operational`. Memory do AI đề
xuất vào ở `pending_review`; người dùng duyệt. Có quota, version, scan injection,
và retention (`expires_at`). Lịch sử chi tiết KHÔNG nhét hết vào prompt — truy
hồi on-demand bằng `search_history`.
"""
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import AssistantFeedback, AssistantMessage, AssistantThread, LongTermMemory
from .prompt_guard import scan as guard_scan

MEMORY_QUOTA = {LongTermMemory.SCOPE_PROFILE: 20, LongTermMemory.SCOPE_OPERATIONAL: 60}


def _quota(scope):
    default = MEMORY_QUOTA.get(scope, 40)
    return int(getattr(settings, "ASSISTANT_MEMORY_QUOTA", {}).get(scope, default)) \
        if isinstance(getattr(settings, "ASSISTANT_MEMORY_QUOTA", None), dict) else default


def _mem(row):
    return {"id": row.pk, "scope": row.scope, "kind": row.kind, "status": row.status,
            "key": row.key, "value": row.value, "source": row.source,
            "version": row.version, "surface": row.surface,
            "expires_at": row.expires_at,
            "created_at": row.created_at, "updated_at": row.updated_at}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def memory_list(request):
    if request.method == "POST":
        value = str(request.data.get("value") or "").strip()
        if not value:
            return Response({"detail": "Thiếu nội dung cần nhớ."}, status=400)
        if guard_scan(value):
            return Response({"detail": "Nội dung có dấu hiệu chèn lệnh; không lưu."}, status=400)

        scope = request.data.get("scope")
        if scope not in dict(LongTermMemory.SCOPE_CHOICES):
            scope = LongTermMemory.SCOPE_OPERATIONAL
        kind = request.data.get("kind")
        if kind not in dict(LongTermMemory.KIND_CHOICES):
            kind = LongTermMemory.KIND_FACT

        active = LongTermMemory.objects.filter(
            user=request.user, scope=scope, status=LongTermMemory.STATUS_ACTIVE).count()
        key = str(request.data.get("key") or "").strip()[:80]
        exists = key and LongTermMemory.objects.filter(
            user=request.user, scope=scope, key=key).exists()
        if not exists and active >= _quota(scope):
            return Response({"detail": f"Đã đạt giới hạn {_quota(scope)} ghi nhớ cho "
                             f"nhóm '{scope}'. Xoá bớt trước khi thêm."}, status=409)

        # Người dùng tự tạo -> active ngay. (AI đề xuất đi qua background review,
        # tạo row status=pending_review, source=radar_ai — không qua endpoint này.)
        defaults = {"kind": kind, "value": value[:4000], "status": LongTermMemory.STATUS_ACTIVE,
                    "surface": str(request.data.get("surface") or "")[:20], "source": "user"}
        if key:
            row, created = LongTermMemory.objects.get_or_create(
                user=request.user, scope=scope, key=key, defaults=defaults)
            if not created:
                row.value = defaults["value"]
                row.kind = kind
                row.status = LongTermMemory.STATUS_ACTIVE
                row.version += 1
                row.save(update_fields=["value", "kind", "status", "version", "updated_at"])
        else:
            row = LongTermMemory.objects.create(user=request.user, scope=scope, **defaults)
        return Response(_mem(row), status=201)

    rows = LongTermMemory.objects.filter(user=request.user)
    if request.query_params.get("scope") in dict(LongTermMemory.SCOPE_CHOICES):
        rows = rows.filter(scope=request.query_params["scope"])
    if request.query_params.get("status") in dict(LongTermMemory.STATUS_CHOICES):
        rows = rows.filter(status=request.query_params["status"])
    return Response({
        "results": [_mem(r) for r in rows],
        "quota": {s: _quota(s) for s, _ in LongTermMemory.SCOPE_CHOICES},
        "pending": LongTermMemory.objects.filter(
            user=request.user, status=LongTermMemory.STATUS_PENDING).count(),
    })


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def memory_detail(request, memory_id):
    row = LongTermMemory.objects.filter(pk=memory_id, user=request.user).first()
    if row is None:
        return Response({"detail": "Không tìm thấy."}, status=404)
    if request.method == "DELETE":
        row.delete()
        return Response(status=204)

    fields = ["updated_at", "version"]
    if "value" in request.data:
        value = str(request.data.get("value") or "").strip()[:4000]
        if guard_scan(value):
            return Response({"detail": "Nội dung có dấu hiệu chèn lệnh."}, status=400)
        row.value = value
        fields.append("value")
    if "key" in request.data:
        row.key = str(request.data.get("key") or "").strip()[:80]
        fields.append("key")
    if request.data.get("status") in (LongTermMemory.STATUS_ACTIVE, LongTermMemory.STATUS_REJECTED):
        # Người dùng duyệt/bỏ một đề xuất của AI.
        row.status = request.data["status"]
        fields.append("status")
    row.version += 1
    row.save(update_fields=fields)
    return Response(_mem(row))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_feedback(request):
    rating = str(request.data.get("rating") or "").lower()
    if rating not in dict(AssistantFeedback.RATING_CHOICES):
        return Response({"detail": "rating phải là up hoặc down."}, status=400)

    message = thread = None
    message_id = request.data.get("message_id")
    if message_id:
        message = AssistantMessage.objects.filter(
            pk=message_id, thread__user=request.user).select_related("thread").first()
        if message is None:
            return Response({"detail": "Không tìm thấy tin nhắn của bạn."}, status=404)
        thread = message.thread
    conv_id = request.data.get("conversation_id")
    if thread is None and conv_id:
        thread = AssistantThread.objects.filter(
            user=request.user, thread_id=str(conv_id)).order_by("-updated_at").first()

    fields = {
        "thread": thread, "rating": rating,
        "reason": str(request.data.get("reason") or "")[:500],
        "question": str(request.data.get("question") or "")[:4000]
        or (_prev_user_text(message) if message else ""),
        "answer": str(request.data.get("answer") or "")[:4000]
        or (message.content if message else ""),
        "surface": (thread.surface if thread else ""),
    }
    if message is not None:
        row, _ = AssistantFeedback.objects.update_or_create(
            message=message, user=request.user, defaults=fields)
    else:
        row = AssistantFeedback.objects.create(message=None, user=request.user, **fields)
    return Response({"ok": True, "id": row.pk, "rating": row.rating}, status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_history(request):
    """Truy hồi lịch sử hội thoại theo từ khoá — CHỈ của chính người dùng (§15 GĐ5).

    Dùng khi cần chi tiết cũ, thay vì nhét toàn bộ lịch sử vào prompt.
    """
    q = str(request.query_params.get("q") or "").strip()
    if len(q) < 2:
        return Response({"detail": "Từ khoá quá ngắn."}, status=400)
    surface = request.query_params.get("surface")
    messages = (AssistantMessage.objects
                .filter(thread__user=request.user, content__icontains=q)
                .select_related("thread").order_by("-created_at"))
    if surface in dict(AssistantThread.SURFACE_CHOICES):
        messages = messages.filter(thread__surface=surface)
    return Response({"results": [{
        "message_id": m.pk, "role": m.role,
        "snippet": _snippet(m.content, q),
        "conversation_id": m.thread.thread_id, "surface": m.thread.surface,
        "title": m.thread.title, "created_at": m.created_at,
    } for m in messages[:30]]})


def _snippet(text, q, width=120):
    text = str(text or "")
    idx = text.lower().find(q.lower())
    if idx < 0:
        return text[:width]
    start = max(0, idx - width // 2)
    return ("…" if start else "") + text[start:start + width] + "…"


def _prev_user_text(message):
    prev = (AssistantMessage.objects
            .filter(thread=message.thread, role="user", created_at__lte=message.created_at)
            .order_by("-created_at", "-pk").first())
    return prev.content if prev else ""
