# -*- coding: utf-8 -*-
"""Đọc `ImportBatch`/`ImportRow` cho giao diện Hub."""
from rest_framework import serializers

from .models import ImportBatch, ImportRow


class ImportRowSerializer(serializers.ModelSerializer):
    matched_person_name = serializers.SerializerMethodField()
    person_id = serializers.SerializerMethodField()

    class Meta:
        model = ImportRow
        fields = ["id", "row_number", "raw", "fields", "entity_key",
                  "validation_status", "errors", "matched_person_id",
                  "matched_person_name", "source_record_id", "person_id",
                  "cv_filename", "cv_sha256", "ai_extracted"]

    def get_matched_person_name(self, row):
        return row.matched_person.display_name if row.matched_person_id else ""

    def get_person_id(self, row):
        rec = row.source_record
        return rec.person_id if rec is not None else None


class ImportBatchSerializer(serializers.ModelSerializer):
    rows = serializers.SerializerMethodField()

    class Meta:
        model = ImportBatch
        fields = ["id", "kind", "source_label", "original_filename", "status",
                  "row_count", "valid_count", "duplicate_count", "invalid_count",
                  "committed_count", "error_count", "created_by_name",
                  "created_at", "updated_at", "rows"]

    def get_rows(self, batch):
        if not self.context.get("with_rows"):
            return None
        return ImportRowSerializer(batch.rows.all(), many=True).data
