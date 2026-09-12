# -*- coding: utf-8 -*-
from rest_framework import serializers

from .models import FilterHistory, SavedView


class SavedViewSerializer(serializers.ModelSerializer):
    module_label = serializers.CharField(source="get_module_display", read_only=True)

    class Meta:
        model = SavedView
        fields = ["id", "module", "module_label", "name", "filters",
                  "created_at", "last_used_at"]
        read_only_fields = ["created_at", "last_used_at"]


class FilterHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = FilterHistory
        fields = ["id", "module", "filters", "used_at"]
        read_only_fields = ["used_at"]
