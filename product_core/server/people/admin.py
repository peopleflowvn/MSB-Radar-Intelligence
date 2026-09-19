# -*- coding: utf-8 -*-
"""Trang quản trị People Core.

Màn hình quan trọng nhất ở đây là hàng đợi **Xung đột định danh**: nơi con người
quyết định hai hồ sơ có phải cùng một người hay không. Master Plan mục 12 nói rõ
AI không được quyết việc này.
"""
from django.contrib import admin, messages
from django.utils.html import format_html

from . import resolution
from .models import (ContactMention, Document, DocumentTextLink, Identity, IdentityConflict,
                     Interaction, Opportunity, ParsedTextVersion, Person, PersonLink,
                     Relationship, Signal)


class IdentityInline(admin.TabularInline):
    model = Identity
    extra = 0
    fields = ("kind", "value", "raw_value", "first_seen_at")
    readonly_fields = ("first_seen_at",)


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("display_name", "primary_email", "primary_phone", "headline",
                    "location", "so_nguon", "canh_bao", "updated_at")
    list_filter = ("needs_review", "location")
    search_fields = ("display_name", "normalized_name", "primary_email", "primary_phone")
    readonly_fields = ("normalized_name", "created_at", "updated_at", "merged_into")
    inlines = [IdentityInline]

    @admin.display(description="Nguồn")
    def so_nguon(self, obj):
        return obj.source_records.count()

    @admin.display(description="Trạng thái")
    def canh_bao(self, obj):
        if obj.merged_into_id:
            return format_html('<span style="color:#888">đã gộp vào #{}</span>',
                               obj.merged_into_id)
        if obj.needs_review:
            return format_html('<b style="color:#c00">cần xem lại</b>')
        return "—"


@admin.register(Identity)
class IdentityAdmin(admin.ModelAdmin):
    list_display = ("kind", "value", "person", "first_seen_at")
    list_filter = ("kind",)
    search_fields = ("value", "raw_value", "person__display_name")
    readonly_fields = ("first_seen_at", "last_seen_at")


@admin.register(IdentityConflict)
class IdentityConflictAdmin(admin.ModelAdmin):
    list_display = ("id", "danh_sach_person", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = ("people", "evidence", "source_record_id", "created_at", "resolved_at")
    actions = ["gop_vao_person_cu_nhat", "bo_qua_hai_nguoi_khac_nhau"]

    @admin.display(description="Các Person")
    def danh_sach_person(self, obj):
        return ", ".join(f"#{p.pk} {p.display_name}" for p in obj.people.all())

    @admin.action(description="Gộp: đây là CÙNG một người")
    def gop_vao_person_cu_nhat(self, request, queryset):
        """Gộp vào Person được tạo sớm nhất — nó mang lịch sử dài nhất."""
        merged = 0
        for conflict in queryset.filter(status=IdentityConflict.STATUS_OPEN):
            resolution.resolve_identity_conflict(
                conflict, "merge", note=f"Gộp bởi {request.user}")
            merged += 1
        self.message_user(request, f"Đã gộp {merged} xung đột.",
                          level=messages.SUCCESS if merged else messages.WARNING)

    @admin.action(description="Bỏ qua: đây là HAI người khác nhau")
    def bo_qua_hai_nguoi_khac_nhau(self, request, queryset):
        count = 0
        for conflict in queryset.filter(status=IdentityConflict.STATUS_OPEN):
            resolution.resolve_identity_conflict(
                conflict, "dismiss", note=f"Bỏ qua bởi {request.user}")
            count += 1
        self.message_user(request, f"Đã bỏ qua {count} xung đột.")


@admin.register(Signal)
class SignalAdmin(admin.ModelAdmin):
    list_display = ("signal_type", "person", "domain", "confidence", "status", "observed_at")
    list_filter = ("domain", "status", "signal_type")
    search_fields = ("person__display_name", "signal_type")
    date_hierarchy = "observed_at"


@admin.register(Relationship)
class RelationshipAdmin(admin.ModelAdmin):
    list_display = ("person", "domain", "state", "owner", "updated_at")
    list_filter = ("domain", "state")
    search_fields = ("person__display_name", "owner")


@admin.register(ContactMention)
class ContactMentionAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "phone", "kind", "extractor", "confidence",
                    "status", "subject", "linked_person", "created_at")
    list_filter = ("status", "kind", "extractor")
    search_fields = ("full_name", "email", "phone", "company",
                     "subject__display_name")
    readonly_fields = ("fingerprint", "created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(PersonLink)
class PersonLinkAdmin(admin.ModelAdmin):
    list_display = ("subject", "kind", "related", "confidence", "created_by", "created_at")
    list_filter = ("kind",)
    search_fields = ("subject__display_name", "related__display_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Interaction)
class InteractionAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "person", "domain", "action", "actor_name")
    list_filter = ("domain", "action")
    search_fields = ("person__display_name", "actor_name")
    date_hierarchy = "occurred_at"


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ("title", "person", "domain", "score", "confidence", "owner", "status")
    list_filter = ("domain", "status")
    search_fields = ("title", "person__display_name", "owner")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("filename", "person", "document_type", "source", "parse_status",
                    "parse_provider", "created_at")
    list_filter = ("document_type", "source", "parse_status", "parse_provider")
    search_fields = ("filename", "person__display_name", "sha256")
    readonly_fields = ("sha256", "created_at")


@admin.register(ParsedTextVersion)
class ParsedTextVersionAdmin(admin.ModelAdmin):
    list_display = ("person", "text_hash", "text_length", "created_at")
    search_fields = ("person__display_name", "text_hash", "text")
    readonly_fields = ("text_hash", "created_at")


@admin.register(DocumentTextLink)
class DocumentTextLinkAdmin(admin.ModelAdmin):
    list_display = ("document", "text_version", "origins", "provider", "model",
                    "quality_score", "created_at")
    list_filter = ("provider",)
