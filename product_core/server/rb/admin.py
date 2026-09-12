# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import ProductInterest, RBOpportunity, RBProfile


class ProductInterestInline(admin.TabularInline):
    model = ProductInterest
    extra = 0
    fields = ("product", "confidence", "source", "observed_at")


@admin.register(RBProfile)
class RBProfileAdmin(admin.ModelAdmin):
    list_display = ("person", "lead_status", "segment", "sales_owner_name",
                    "last_contact_at", "updated_at")
    list_filter = ("lead_status", "segment")
    search_fields = ("person__display_name", "occupation", "employer")
    raw_id_fields = ("person",)
    inlines = [ProductInterestInline]


@admin.register(RBOpportunity)
class RBOpportunityAdmin(admin.ModelAdmin):
    list_display = ("person", "product", "status", "confidence",
                    "assigned_to_name", "created_at")
    list_filter = ("status", "product")
    search_fields = ("person__display_name", "need")
    raw_id_fields = ("person", "signal")
