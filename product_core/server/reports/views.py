# -*- coding: utf-8 -*-
"""API vận hành & báo cáo (Master Plan mục 15, PHASE 15)."""
import hashlib
import json
from accounts import roles
from accounts.permissions import RequiresReports
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import overview as overview_module
from .models import FilterHistory, MODULE_CHOICES, SavedView
from .serializers import FilterHistorySerializer, SavedViewSerializer


@api_view(["GET"])
@permission_classes([RequiresReports])
def overview(request):
    """Trang vận hành gộp — chỉ Admin/Manager, xem docstring `accounts/roles.py`."""
    return Response(overview_module.collect())


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def saved_view_list(request):
    """Bộ lọc đã lưu của CHÍNH người dùng — không phải trang vận hành.

    Quyền theo `module` trong dữ liệu, không phải `RequiresReports`: một
    recruiter lưu bộ lọc Talent hoàn toàn không cần vào được trang vận hành.
    """
    if request.method == "POST":
        module = str(request.data.get("module") or "")
        if module not in dict(MODULE_CHOICES):
            return Response({"detail": f"Module không hợp lệ: {module}"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not roles.can_access(request.user, module):
            return Response(
                {"detail": f"Bạn không có quyền lưu bộ lọc cho {module}."},
                status=status.HTTP_403_FORBIDDEN)

        name = str(request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "Cần đặt tên cho bộ lọc."},
                            status=status.HTTP_400_BAD_REQUEST)
        filters = request.data.get("filters")
        if not isinstance(filters, dict):
            filters = {}

        view, created = SavedView.objects.update_or_create(
            owner=request.user, module=module, name=name[:150],
            defaults={"filters": filters})
        return Response(SavedViewSerializer(view).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    queryset = SavedView.objects.filter(owner=request.user)
    if request.query_params.get("module"):
        queryset = queryset.filter(module=request.query_params["module"])
    return Response({"results": SavedViewSerializer(queryset, many=True).data})


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def saved_view_detail(request, view_id):
    view = get_object_or_404(SavedView, pk=view_id, owner=request.user)

    if request.method == "DELETE":
        view.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # POST = "mở lại view này" — chỉ cập nhật `last_used_at` để danh sách xếp
    # theo view hay dùng lên đầu; bộ lọc thật do frontend tự áp dụng lại.
    view.last_used_at = timezone.now()
    view.save(update_fields=["last_used_at"])
    return Response(SavedViewSerializer(view).data)


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def filter_history(request):
    """Lịch sử bộ lọc đã chạy của chính người dùng; giữ 20 mục gần nhất."""
    module = str(request.data.get("module") if request.method == "POST"
                 else request.query_params.get("module") or "")
    if module not in dict(MODULE_CHOICES):
        return Response({"detail": f"Module không hợp lệ: {module}"},
                        status=status.HTTP_400_BAD_REQUEST)
    if not roles.can_access(request.user, module):
        return Response({"detail": f"Bạn không có quyền dùng bộ lọc {module}."},
                        status=status.HTTP_403_FORBIDDEN)
    queryset = FilterHistory.objects.filter(owner=request.user, module=module)
    if request.method == "DELETE":
        queryset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "GET":
        return Response({"results": FilterHistorySerializer(queryset[:20], many=True).data})

    filters = request.data.get("filters")
    if not isinstance(filters, dict) or not filters:
        return Response({"detail": "Bộ lọc không hợp lệ."},
                        status=status.HTTP_400_BAD_REQUEST)
    canonical = json.dumps(filters, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    if len(canonical.encode("utf-8")) > 20_000:
        return Response({"detail": "Bộ lọc vượt quá kích thước cho phép."},
                        status=status.HTTP_400_BAD_REQUEST)
    signature = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    row, _ = FilterHistory.objects.update_or_create(
        owner=request.user, module=module, signature=signature,
        defaults={"filters": filters, "used_at": timezone.now()})
    stale_ids = list(FilterHistory.objects.filter(owner=request.user, module=module)
                     .order_by("-used_at").values_list("id", flat=True)[20:])
    if stale_ids:
        FilterHistory.objects.filter(id__in=stale_ids).delete()
    return Response(FilterHistorySerializer(row).data, status=status.HTTP_201_CREATED)
