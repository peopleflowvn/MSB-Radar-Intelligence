# -*- coding: utf-8 -*-
"""Dùng GLM cho Talent judge vì qwen không đủ rate capacity cho nhiều batch."""
from django.db import migrations


MARKER = "migration 0029"
TASK = "talent_answer_judge"
OLD = ("greennode", "qwen/qwen3.7-plus")
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
        provider=OLD[0], model=OLD[1], updated_by="migration 0025")


class Migration(migrations.Migration):
    dependencies = [("ai", "0028_route_demo_stable_compose")]
    operations = [migrations.RunPython(forward, backward)]
