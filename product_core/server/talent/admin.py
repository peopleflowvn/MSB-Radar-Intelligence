# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import Pool, PoolMembership, Tag, TalentProfile


@admin.register(TalentProfile)
class TalentProfileAdmin(admin.ModelAdmin):
    list_display = ("person", "current_title", "current_company", "years_experience",
                    "location", "owner_name", "last_source_at")
    list_filter = ("seniority", "location")
    search_fields = ("person__display_name", "current_title", "current_company")
    readonly_fields = ("curated_fields", "derived_at", "created_at", "updated_at")
    filter_horizontal = ("tags",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "so_nguoi")
    search_fields = ("name", "slug")
    readonly_fields = ("slug",)

    @admin.display(description="Số người")
    def so_nguoi(self, obj):
        return obj.talents.count()


class PoolMembershipInline(admin.TabularInline):
    model = PoolMembership
    extra = 0
    fields = ("person", "added_by_name", "note", "added_at")
    readonly_fields = ("added_by_name", "added_at")


@admin.register(Pool)
class PoolAdmin(admin.ModelAdmin):
    list_display = ("name", "owner_name", "so_thanh_vien", "is_archived", "updated_at")
    list_filter = ("is_archived",)
    search_fields = ("name", "description")
    inlines = [PoolMembershipInline]

    @admin.display(description="Thành viên")
    def so_thanh_vien(self, obj):
        return obj.memberships.count()
