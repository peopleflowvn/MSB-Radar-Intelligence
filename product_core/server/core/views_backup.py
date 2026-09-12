# -*- coding: utf-8 -*-
"""API Quản trị Sao lưu Cơ sở dữ liệu lên Cloudflare R2 / Local Storage."""
import logging
from accounts import roles
from django.conf import settings
from django.db.models import Sum
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .backup_service import run_database_backup
from .models import DatabaseBackupLog
from .storage import get_storage

log = logging.getLogger(__name__)


def _serialize_backup(record):
    return {
        "id": record.id,
        "filename": record.filename,
        "storage_key": record.storage_key,
        "storage_backend": record.storage_backend,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "status": record.status,
        "error_message": record.error_message,
        "trigger_type": record.trigger_type,
        "created_by": record.created_by.username if record.created_by else "Hệ thống (Cron)",
        "duration_ms": record.duration_ms,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def backup_list(request):
    """Lấy danh sách các đợt sao lưu CSDL và tổng quan dung lượng."""
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên được xem lịch sử sao lưu."},
                        status=status.HTTP_403_FORBIDDEN)

    qs = DatabaseBackupLog.objects.all().order_by("-created_at")
    total_count = qs.count()
    completed_qs = qs.filter(status=DatabaseBackupLog.STATUS_COMPLETED)
    total_size = completed_qs.aggregate(total=Sum("size_bytes"))["total"] or 0
    latest = completed_qs.first()

    r2_config = getattr(settings, "FILE_STORAGE", {})
    storage = get_storage()
    backend_name = getattr(storage, "name", "local")

    results = [_serialize_backup(r) for r in qs[:50]]

    return Response({
        "summary": {
            "total_backups": total_count,
            "completed_backups": completed_qs.count(),
            "total_size_bytes": total_size,
            "storage_backend": backend_name,
            "r2_bucket": r2_config.get("bucket", ""),
            "r2_configured": bool(r2_config.get("bucket") and r2_config.get("access_key")),
            "schedule": "02:00 & 14:00 hàng ngày (2 lần / ngày)",
            "retention_days": 30,
            "latest_backup": _serialize_backup(latest) if latest else None,
        },
        "results": results,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def backup_trigger(request):
    """Admin chủ động kích hoạt sao lưu tức thì."""
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên được kích hoạt sao lưu."},
                        status=status.HTTP_403_FORBIDDEN)

    try:
        log_entry = run_database_backup(
            trigger_type=DatabaseBackupLog.TRIGGER_MANUAL,
            user=request.user,
            retention_days=30
        )
        return Response(_serialize_backup(log_entry), status=status.HTTP_201_CREATED)
    except Exception as exc:
        log.exception("Lỗi khi admin kích hoạt sao lưu: %s", exc)
        return Response({"detail": f"Sao lưu thất bại: {exc}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def backup_download(request, pk):
    """Tải tệp nén sao lưu CSDL về máy quản trị viên."""
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên được tải bản sao lưu."},
                        status=status.HTTP_403_FORBIDDEN)

    record = DatabaseBackupLog.objects.filter(pk=pk).first()
    if not record:
        return Response({"detail": "Không tìm thấy bản sao lưu."},
                        status=status.HTTP_404_NOT_FOUND)

    if record.status != DatabaseBackupLog.STATUS_COMPLETED:
        return Response({"detail": "Bản sao lưu này chưa hoàn thành hoặc bị lỗi."},
                        status=status.HTTP_400_BAD_REQUEST)

    storage = get_storage()
    if not record.storage_key or not storage.exists(record.storage_key):
        return Response({"detail": "Tệp sao lưu không còn tồn tại trên kho lưu trữ."},
                        status=status.HTTP_404_NOT_FOUND)

    try:
        data = storage.read(record.storage_key)
        response = HttpResponse(data, content_type="application/gzip")
        response["Content-Disposition"] = f'attachment; filename="{record.filename}"'
        response["Content-Length"] = str(len(data))
        return response
    except Exception as exc:
        log.exception("Lỗi khi tải tệp sao lưu: %s", exc)
        return Response({"detail": f"Không thể đọc tệp sao lưu: {exc}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def backup_delete(request, pk):
    """Xoá một bản sao lưu khỏi hệ thống và Cloudflare R2."""
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên được xoá bản sao lưu."},
                        status=status.HTTP_403_FORBIDDEN)

    record = DatabaseBackupLog.objects.filter(pk=pk).first()
    if not record:
        return Response({"detail": "Không tìm thấy bản sao lưu."},
                        status=status.HTTP_404_NOT_FOUND)

    storage = get_storage()
    if record.storage_key and storage.exists(record.storage_key):
        try:
            storage.delete(record.storage_key)
        except Exception as exc:
            log.warning("Lỗi xoá tệp trên storage: %s (%s)", record.storage_key, exc)

    filename = record.filename
    record.delete()
    log.info("Admin %s đã xoá bản sao lưu CSDL %s (ID %s)", request.user.username, filename, pk)
    return Response({"success": True, "message": f"Đã xoá bản sao lưu {filename}."})
