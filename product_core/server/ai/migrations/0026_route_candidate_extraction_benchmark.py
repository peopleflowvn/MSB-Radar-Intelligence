# -*- coding: utf-8 -*-
"""Bóc tách CV (`candidate_extraction`) sang qwen3.7-plus — benchmark 19/09.

Xem `ai/tasks.py::DEFAULT_REASON`. Như 0025: chỉ đổi route do máy quản lý và
còn ở model cũ; lựa chọn tay trong /settings giữ nguyên.
"""
from django.db import migrations

MARKER = "migration 0026"
OLD = ("greennode", "qwen/qwen3.6-flash")
NEW = ("greennode", "qwen/qwen3.7-plus")
TASK = "candidate_extraction"


def _managed(updated_by):
    value = str(updated_by or "")
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
    dependencies = [("ai", "0025_route_benchmark_2026_09_19")]
    operations = [migrations.RunPython(forward, backward)]
