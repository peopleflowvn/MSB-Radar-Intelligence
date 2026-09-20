# -*- coding: utf-8 -*-
"""Dùng GLM làm compose chính để đường demo không hết deadline ở DeepSeek.

Chỉ đổi route còn do migration/benchmark quản lý; lựa chọn thủ công của người
vận hành trong Settings vẫn được giữ nguyên.
"""
from django.db import migrations


MARKER = "migration 0028"
TASK = "talent_answer_compose"
OLD = ("greennode", "deepseek/deepseek-v4-pro")
NEW = ("greennode", "z-ai/glm-5.2-hackathon")


def _managed(value):
    value = str(value or "")
    return not value or value.startswith("migration") or value.startswith("benchmark")


def forward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    for route in Route.objects.filter(task=TASK):
        if _managed(route.updated_by) and (route.provider, route.model) in (OLD, NEW):
            route.provider, route.model = NEW
            route.updated_by = MARKER
            route.save(update_fields=["provider", "model", "updated_by"])


def backward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    Route.objects.filter(task=TASK, updated_by=MARKER).update(
        provider=OLD[0], model=OLD[1], updated_by="migration 0024")


class Migration(migrations.Migration):
    dependencies = [("ai", "0027_answerrun_coverage")]
    operations = [migrations.RunPython(forward, backward)]
