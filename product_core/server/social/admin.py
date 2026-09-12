# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import (Community, SocialAccount, SocialAction, SocialComment,
                     SocialPost)


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ("label", "provider", "handle", "purpose", "is_active",
                    "last_seen_at")
    list_filter = ("provider", "purpose", "is_active")


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "topic", "member_count", "is_active",
                    "last_scanned_at")
    list_filter = ("provider", "is_active")
    search_fields = ("name", "external_id", "topic")


class SocialCommentInline(admin.TabularInline):
    model = SocialComment
    extra = 0
    fields = ("author_name", "content", "posted_at")


@admin.register(SocialPost)
class SocialPostAdmin(admin.ModelAdmin):
    list_display = ("author_name", "top_domain", "status", "person",
                    "community", "posted_at")
    list_filter = ("status", "provider", "intent_fallback")
    search_fields = ("author_name", "content")
    raw_id_fields = ("person", "community")
    readonly_fields = ("intent", "intent_reason", "contacts")
    inlines = [SocialCommentInline]


@admin.register(SocialAction)
class SocialActionAdmin(admin.ModelAdmin):
    list_display = ("kind", "status", "created_by_name", "posted_at", "created_at")
    list_filter = ("kind", "status")
    raw_id_fields = ("post", "community", "hiring_need")
