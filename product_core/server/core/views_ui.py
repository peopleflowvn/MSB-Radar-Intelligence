# -*- coding: utf-8 -*-
"""Endpoint cho giao diện Hub (React). Xác thực bằng phiên đăng nhập Django.

Tách khỏi views.py một cách có chủ đích: hai nhóm này có đối tượng gọi khác
nhau (máy vs người), cách xác thực khác nhau, và nhịp thay đổi khác nhau. Gộp
chung là con đường ngắn nhất tới việc vô tình mở một endpoint quản trị cho khoá
API của Edge.
"""
from accounts import roles
from accounts.permissions import RequiresEdgeOps
from django.db.models import Count
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Edge, SourceRecord, WorkflowStage
from .serializers import SourceRecordSerializer

MAX_PAGE_SIZE = 200

DEFAULT_STAGES = {
    "talent": [
        ("pending", "Mới trong danh sách"), ("contacting", "Đang tiếp cận"),
        ("responded", "Đã phản hồi"), ("interested", "Có quan tâm"),
        ("not_interested", "Chưa quan tâm"), ("unreachable", "Không liên hệ được"),
        ("submitted", "Hoàn tất mục tiêu"), ("returned", "Đưa về chăm sóc dài hạn")],
    "rb": [
        ("new", "Mới"), ("accepted", "Đã nhận"),
        ("contacting", "Đang liên hệ"), ("won", "Thành công"),
        ("lost", "Không thành")],
}


def _workflow_manager(user):
    return bool(roles.roles_of(user) & {roles.ADMIN, roles.MANAGER})


def _ensure_workflow_stages():
    for domain, rows in DEFAULT_STAGES.items():
        for position, (code, label) in enumerate(rows):
            WorkflowStage.objects.get_or_create(
                domain=domain, code=code,
                defaults={"label": label, "position": position,
                          "is_terminal": code in {"submitted", "returned", "won", "lost"},
                          "requires_reason": code in {"returned", "lost"}})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def workflow_stages(request):
    if not _workflow_manager(request.user):
        return Response({"detail": "Chỉ Admin/Manager được quản lý pipeline."},
                        status=status.HTTP_403_FORBIDDEN)
    _ensure_workflow_stages()
    if request.method == "PATCH":
        row = WorkflowStage.objects.filter(pk=request.data.get("id")).first()
        if row is None:
            return Response({"detail": "Không tìm thấy bước pipeline."},
                            status=status.HTTP_404_NOT_FOUND)
        for field in ("label", "color"):
            if field in request.data:
                setattr(row, field, str(request.data[field])[:100])
        try:
            if "position" in request.data:
                row.position = max(0, int(request.data["position"] or 0))
            if "sla_hours" in request.data:
                row.sla_hours = (max(1, int(request.data["sla_hours"]))
                                 if request.data["sla_hours"] not in ("", None) else None)
        except (TypeError, ValueError):
            return Response({"detail": "Thứ tự hoặc SLA không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        for field in ("is_terminal", "requires_reason", "is_active"):
            if field in request.data:
                setattr(row, field, bool(request.data[field]))
        if "allowed_next" in request.data:
            allowed = request.data["allowed_next"]
            if not isinstance(allowed, list) or any(not isinstance(code, str) for code in allowed):
                return Response({"detail": "Danh sách bước tiếp theo không hợp lệ."}, status=400)
            valid_codes = set(WorkflowStage.objects.filter(domain=row.domain)
                              .values_list("code", flat=True))
            if not set(allowed).issubset(valid_codes):
                return Response({"detail": "Bước tiếp theo không thuộc cùng pipeline."}, status=400)
            row.allowed_next = allowed
        row.save()
    rows = WorkflowStage.objects.all()
    return Response({"results": [{
        "id": row.id, "domain": row.domain, "code": row.code, "label": row.label,
        "position": row.position, "color": row.color, "is_terminal": row.is_terminal,
        "requires_reason": row.requires_reason, "sla_hours": row.sla_hours,
        "is_active": row.is_active, "allowed_next": row.allowed_next} for row in rows]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def workflow_catalog(request):
    """Public presentation/policy catalog; contains no administrative secrets."""
    _ensure_workflow_stages()
    rows = WorkflowStage.objects.filter(is_active=True)
    return Response({"results": [{
        "id": row.id, "domain": row.domain, "code": row.code,
        "label": row.label, "position": row.position, "color": row.color,
        "is_terminal": row.is_terminal, "requires_reason": row.requires_reason,
        "sla_hours": row.sla_hours, "is_active": row.is_active,
        "allowed_next": row.allowed_next} for row in rows]})


@api_view(["GET"])
@permission_classes([RequiresEdgeOps])
def edge_list(request):
    rows = []
    for edge in Edge.objects.all():
        rows.append({
            "id": edge.pk,
            "label": edge.label,
            "edge_id": edge.edge_id or "",
            "hostname": edge.hostname,
            "app_version": edge.app_version,
            "is_active": edge.is_active,
            "registered_at": edge.registered_at,
            "last_seen_at": edge.last_seen_at,
            "record_count": edge.source_records.count(),
        })
    return Response({"results": rows})


@api_view(["GET"])
@permission_classes([RequiresEdgeOps])
def source_record_list(request):
    queryset = SourceRecord.objects.select_related("edge")

    search = str(request.query_params.get("search") or "").strip()
    if search:
        from django.db.models import Q
        queryset = queryset.filter(
            Q(fullname__icontains=search) | Q(email__icontains=search)
            | Q(phone__icontains=search) | Q(position__icontains=search)
            | Q(entity_key__icontains=search)
            | Q(edge__edge_id__icontains=search) | Q(edge__label__icontains=search))

    source = str(request.query_params.get("source") or "").strip()
    if source:
        queryset = queryset.filter(source=source)

    try:
        limit = min(MAX_PAGE_SIZE, max(1, int(request.query_params.get("limit", 50))))
        offset = max(0, int(request.query_params.get("offset", 0)))
    except (TypeError, ValueError):
        limit, offset = 50, 0

    total = queryset.count()
    rows = SourceRecordSerializer(queryset[offset:offset + limit], many=True).data
    return Response({"count": total, "results": rows})


@api_view(["GET"])
@permission_classes([RequiresEdgeOps])
def summary(request):
    by_source = list(SourceRecord.objects.values("source")
                     .annotate(count=Count("id")).order_by("-count"))
    return Response({
        "edges": Edge.objects.count(),
        "edges_registered": Edge.objects.exclude(edge_id=None).count(),
        "source_records": SourceRecord.objects.count(),
        "pending_resolution": SourceRecord.objects.filter(
            status=SourceRecord.STATUS_PENDING).count(),
        "by_source": by_source,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def capture_stats(request):
    """Năng lực thu thập và hợp nhất — số liệu cho dashboard và cho pitch.

    Mở cho **mọi tài khoản đã đăng nhập**, khác với `summary` (chỉ Edge Ops) và
    `reports/overview` (chỉ Admin/Manager). Lý do: đây không phải dữ liệu vận
    hành nội bộ mà là câu trả lời cho câu hỏi *"kho này có gì"* — recruiter cần
    biết trước khi tin vào kết quả tìm kiếm, và RM cần biết trước khi tin vào
    danh sách cơ hội.

    Không có dữ liệu cá nhân nào trong phản hồi này: toàn bộ là số đếm.
    """
    from . import capture

    return Response(capture.collect())
