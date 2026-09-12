# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import (CanonicalAlias, CanonicalEntry, CanonicalNamespace,
                     ExtractedFact, ExtractionJob, ExtractionRun,
                     MaterializedProfile, ReviewItem)


@admin.register(CanonicalNamespace)
class CanonicalNamespaceAdmin(admin.ModelAdmin):
    list_display = ("key", "label", "normalization_version", "fold_diacritics", "active")


@admin.register(CanonicalEntry)
class CanonicalEntryAdmin(admin.ModelAdmin):
    list_display = ("namespace", "code", "label", "parent", "active")
    list_filter = ("namespace", "active")
    search_fields = ("code", "label")


@admin.register(CanonicalAlias)
class CanonicalAliasAdmin(admin.ModelAdmin):
    list_display = ("namespace", "alias_norm", "entry", "status", "source", "approved_by")
    list_filter = ("namespace", "status", "source")
    search_fields = ("alias_norm", "alias_raw")


@admin.register(ExtractionRun)
class ExtractionRunAdmin(admin.ModelAdmin):
    list_display = ("person", "status", "extractor", "dry_run", "started_at", "finished_at")
    list_filter = ("status", "extractor", "dry_run")


@admin.register(ExtractedFact)
class ExtractedFactAdmin(admin.ModelAdmin):
    list_display = ("person", "field", "canonical_code", "source_kind", "status",
                    "is_current", "confidence", "observed_at")
    list_filter = ("field", "source_kind", "status", "is_current")
    search_fields = ("raw_value", "normalized_value", "canonical_code")


@admin.register(ReviewItem)
class ReviewItemAdmin(admin.ModelAdmin):
    list_display = ("person", "field", "reason", "status", "created_at", "resolved_by")
    list_filter = ("reason", "status")


@admin.register(ExtractionJob)
class ExtractionJobAdmin(admin.ModelAdmin):
    list_display = ("person", "status", "batch", "attempts", "lease_until", "worker")
    list_filter = ("status", "batch")


@admin.register(MaterializedProfile)
class MaterializedProfileAdmin(admin.ModelAdmin):
    list_display = ("person", "projection_version", "fact_count", "built_at")
