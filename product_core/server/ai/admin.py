# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import LLMCall, ProviderConfig, TaskModelRoute


@admin.register(ProviderConfig)
class ProviderConfigAdmin(admin.ModelAdmin):
    """Bản dự phòng của màn hình Cài đặt AI trên React.

    Giữ lại để sửa được khi giao diện React hỏng, và để xem ai đổi gì lúc nào.
    Ô nhập khoá cố ý KHÔNG có ở đây: khoá chỉ đặt qua API
    (`PATCH /api/v1/ai/providers/<tên>/`), nơi nó được mã hoá trước khi ghi.
    """

    list_display = ("provider", "enabled", "priority", "model", "api_key_hint",
                    "last_check_ok", "updated_by", "updated_at")
    list_filter = ("enabled", "provider")
    readonly_fields = ("api_key_hint", "last_checked_at", "last_check_ok",
                       "last_check_detail", "updated_by", "created_at", "updated_at")
    fields = ("provider", "enabled", "priority", "base_url", "model", "timeout",
              "api_key_hint", "last_checked_at", "last_check_ok", "last_check_detail",
              "updated_by", "created_at", "updated_at")


@admin.register(TaskModelRoute)
class TaskModelRouteAdmin(admin.ModelAdmin):
    list_display = ("task", "provider", "model", "enabled", "updated_by", "updated_at")
    list_filter = ("enabled", "provider")
    search_fields = ("task", "model")


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = ("created_at", "provider", "model", "task", "total_tokens",
                    "latency_ms", "ok")
    list_filter = ("provider", "ok", "task")
    search_fields = ("model", "task", "error")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
