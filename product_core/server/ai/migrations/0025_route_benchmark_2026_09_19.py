# -*- coding: utf-8 -*-
"""Đổi ① hiểu câu hỏi, ③ đọc CV và task Growth sang qwen3.7-plus.

Căn cứ: benchmark 19/09 trên dữ liệu production — xem `ai/tasks.py::_QWEN_PLUS`
và `DEFAULT_REASON`. ⑤ viết câu trả lời GIỮ deepseek-v4-pro.

Chỉ cập nhật route vẫn do máy quản lý (`updated_by` là một migration, rỗng,
hoặc đợt benchmark) và còn đang ở model cũ. Route người vận hành tự chọn trong
/settings không bị ghi đè.
"""
from django.db import migrations

MARKER = "migration 0025"
OLD = ("greennode", "qwen/qwen3.6-flash")
NEW = ("greennode", "qwen/qwen3.7-plus")
TASKS = ("talent_answer_plan", "talent_answer_judge", "rb_prospect_search")


def _managed(updated_by):
    value = str(updated_by or "")
    return not value or value.startswith("migration") or value.startswith("benchmark")


def forward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    for route in Route.objects.filter(task__in=TASKS):
        if not _managed(getattr(route, "updated_by", "")):
            continue
        if (route.provider, route.model) in (OLD, NEW):
            route.provider, route.model = NEW
            route.updated_by = MARKER
            route.save(update_fields=["provider", "model", "updated_by"])


def backward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    Route.objects.filter(task__in=TASKS, updated_by=MARKER).update(
        provider=OLD[0], model=OLD[1], updated_by="migration 0024")


class Migration(migrations.Migration):
    dependencies = [("ai", "0024_route_greennode_primary")]
    operations = [migrations.RunPython(forward, backward)]
