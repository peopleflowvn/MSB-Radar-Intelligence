# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import FilterHistory, SavedView


@admin.register(SavedView)
class SavedViewAdmin(admin.ModelAdmin):
    list_display = ("name", "module", "owner", "created_at", "last_used_at")
    list_filter = ("module",)
    raw_id_fields = ("owner",)


@admin.register(FilterHistory)
class FilterHistoryAdmin(admin.ModelAdmin):
    list_display = ("owner", "module", "used_at")
    list_filter = ("module",)
    raw_id_fields = ("owner",)
    readonly_fields = ("signature", "filters", "used_at")
