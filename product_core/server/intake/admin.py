# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import ImportBatch, ImportRow


class ImportRowInline(admin.TabularInline):
    model = ImportRow
    extra = 0
    fields = ("row_number", "validation_status", "entity_key", "cv_filename")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "source_label", "status", "row_count",
                    "committed_count", "created_by_name", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("source_label", "original_filename", "created_by_name")
    inlines = [ImportRowInline]


@admin.register(ImportRow)
class ImportRowAdmin(admin.ModelAdmin):
    list_display = ("id", "batch", "row_number", "validation_status",
                    "entity_key", "ai_extracted")
    list_filter = ("validation_status", "ai_extracted")
    search_fields = ("entity_key", "cv_filename")
