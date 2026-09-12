# -*- coding: utf-8 -*-
"""Trang quản trị — nơi cấp và thu hồi khoá API cho Edge."""
from django.contrib import admin, messages
from django.utils.html import format_html

from .models import Edge, EdgeApiKey, SourceRecord


class EdgeApiKeyInline(admin.TabularInline):
    model = EdgeApiKey
    extra = 0
    fields = ("name", "prefix", "created_at", "last_used_at", "revoked_at")
    readonly_fields = ("prefix", "created_at", "last_used_at")
    can_delete = False


@admin.register(Edge)
class EdgeAdmin(admin.ModelAdmin):
    list_display = ("label", "edge_id_short", "hostname", "app_version", "is_active",
                    "last_seen_at", "record_count")
    list_filter = ("is_active",)
    search_fields = ("label", "edge_id", "hostname")
    readonly_fields = ("edge_id", "hostname", "app_version", "registered_at",
                       "last_seen_at", "created_at", "updated_at")
    inlines = [EdgeApiKeyInline]
    actions = ["cap_khoa_moi", "vo_hieu_hoa", "kich_hoat"]

    @admin.display(description="Mã Edge")
    def edge_id_short(self, obj):
        return f"{obj.edge_id[:12]}…" if obj.edge_id else "chưa đăng ký"

    @admin.display(description="Số bản ghi")
    def record_count(self, obj):
        return obj.source_records.count()

    @admin.action(description="Cấp khoá API mới")
    def cap_khoa_moi(self, request, queryset):
        for edge in queryset:
            _, raw_key = EdgeApiKey.issue(edge, name=f"Cấp bởi {request.user}")
            # Khoá thô chỉ hiện ĐÚNG MỘT LẦN ở đây. Hub chỉ lưu hash nên không
            # có cách nào lấy lại; mất thì cấp khoá khác.
            self.message_user(
                request,
                format_html(
                    "Khoá API mới cho <b>{}</b> — chép ngay, sẽ không hiện lại:"
                    "<br><code style='font-size:14px'>{}</code>", edge.label, raw_key),
                level=messages.WARNING)

    @admin.action(description="Vô hiệu hoá Edge đã chọn")
    def vo_hieu_hoa(self, request, queryset):
        self.message_user(request, f"Đã vô hiệu hoá {queryset.update(is_active=False)} Edge.")

    @admin.action(description="Kích hoạt lại Edge đã chọn")
    def kich_hoat(self, request, queryset):
        self.message_user(request, f"Đã kích hoạt {queryset.update(is_active=True)} Edge.")


@admin.register(EdgeApiKey)
class EdgeApiKeyAdmin(admin.ModelAdmin):
    list_display = ("edge", "prefix", "name", "created_at", "last_used_at", "trang_thai")
    list_filter = ("edge",)
    readonly_fields = ("edge", "prefix", "key_hash", "created_at", "last_used_at")
    actions = ["thu_hoi"]

    def has_add_permission(self, request):
        # Khoá phải được cấp qua hành động ở trang Edge, vì chỉ ở đó khoá thô
        # mới được sinh và hiển thị một lần.
        return False

    @admin.display(description="Trạng thái", boolean=True)
    def trang_thai(self, obj):
        return obj.is_active

    @admin.action(description="Thu hồi khoá đã chọn")
    def thu_hoi(self, request, queryset):
        count = 0
        for key in queryset:
            if key.is_active:
                key.revoke()
                count += 1
        self.message_user(request, f"Đã thu hồi {count} khoá.")


@admin.register(SourceRecord)
class SourceRecordAdmin(admin.ModelAdmin):
    list_display = ("fullname", "source", "position", "email", "phone", "edge",
                    "status", "revision", "last_seen_at")
    list_filter = ("status", "source", "edge")
    search_fields = ("fullname", "email", "phone", "position", "entity_key")
    readonly_fields = [f.name for f in SourceRecord._meta.fields]
    date_hierarchy = "last_seen_at"

    def has_add_permission(self, request):
        return False        # dữ liệu chỉ đến từ Edge

    def has_change_permission(self, request, obj=None):
        return False        # bàn nhận là bất biến; sửa tay sẽ lệch với Edge
