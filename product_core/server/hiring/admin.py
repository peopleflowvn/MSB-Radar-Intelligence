# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import Candidacy, HiringNeed, HuntCandidate, HuntRequest


@admin.register(HiringNeed)
class HiringNeedAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "status", "owner_name",
                    "is_calibrated", "updated_at")
    list_filter = ("status",)
    search_fields = ("title", "department", "jd_text")
    readonly_fields = ("created_at", "updated_at", "calibrated_at")


@admin.register(Candidacy)
class CandidacyAdmin(admin.ModelAdmin):
    list_display = ("person", "hiring_need", "state", "score_snapshot",
                    "marked_by_name", "marked_at")
    list_filter = ("state",)
    search_fields = ("person__display_name", "hiring_need__title")
    raw_id_fields = ("person", "hiring_need")


class HuntCandidateInline(admin.TabularInline):
    model = HuntCandidate
    extra = 0
    raw_id_fields = ("person",)
    fields = ("person", "state", "priority", "next_action_at", "note",
              "return_reason", "outreach_sent_at")


@admin.register(HuntRequest)
class HuntRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "priority", "requested_by_name",
                    "assigned_to_name", "created_at")
    list_filter = ("status", "priority")
    raw_id_fields = ("hiring_need",)
    inlines = [HuntCandidateInline]


@admin.register(HuntCandidate)
class HuntCandidateAdmin(admin.ModelAdmin):
    list_display = ("person", "hunt_request", "state", "priority",
                    "next_action_at", "outreach_sent_at", "updated_at")
    list_filter = ("state", "priority")
    search_fields = ("person__display_name",)
    raw_id_fields = ("person", "hunt_request")
