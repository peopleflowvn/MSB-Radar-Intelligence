# -*- coding: utf-8 -*-
"""Đường dẫn API. Phải khớp docs/SYNC.md mục 5 — Edge đã nói giao thức này."""
from django.urls import path

from . import edge_admin, views, views_backup, views_ui

urlpatterns = [
    path("health/", views.liveness, name="liveness"),

    # Edge gọi
    path("edge/health/", views.edge_health, name="edge-health"),
    path("edge/register/", views.edge_register, name="edge-register"),
    path("edge/data-report/", views.edge_data_report, name="edge-data-report"),
    path("edge/sync/", views.edge_sync, name="edge-sync"),
    path("edge/documents/<str:sha256>/", views.edge_document_upload,
         name="edge-document-upload"),

    # Giao diện Hub gọi (đăng nhập bằng phiên)
    path("hub/edges/", views_ui.edge_list, name="hub-edges"),
    path("hub/source-records/", views_ui.source_record_list, name="hub-source-records"),
    path("hub/summary/", views_ui.summary, name="hub-summary"),
    path("hub/capture/", views_ui.capture_stats, name="hub-capture"),
    path("workflows/stages/", views_ui.workflow_stages, name="workflow-stages"),
    path("workflows/catalog/", views_ui.workflow_catalog, name="workflow-catalog"),

    # Sao lưu CSDL lên Cloudflare R2 & Quản trị
    path("backups/", views_backup.backup_list, name="core-backups-list"),
    path("backups/trigger/", views_backup.backup_trigger, name="core-backups-trigger"),
    path("backups/<int:pk>/download/", views_backup.backup_download, name="core-backups-download"),
    path("backups/<int:pk>/", views_backup.backup_delete, name="core-backups-delete"),

    # Tự phục vụ tạo Edge + cấp/thu hồi khoá API (core/edge_admin.py).
    path("edge-admin/edges/", edge_admin.edge_collection, name="edge-admin-edges"),
    path("edge-admin/edges/<int:edge_id>/", edge_admin.edge_detail,
         name="edge-admin-edge-detail"),
    path("edge-admin/edges/<int:edge_id>/keys/", edge_admin.issue_key,
         name="edge-admin-issue-key"),
    path("edge-admin/keys/<int:key_id>/revoke/", edge_admin.revoke_key,
         name="edge-admin-revoke-key"),
]

