# -*- coding: utf-8 -*-
"""Dùng Gemini Flash cho hai chặng kín plan/judge sau benchmark production.

Chỉ đổi route do migration quản lý và còn đúng model mặc định cũ; mọi lựa chọn
thủ công trong /settings được giữ nguyên. Compose vẫn dùng DeepSeek V4 Pro để
ưu tiên chất lượng diễn đạt, còn GreenNode vẫn là fallback của router.
"""
from django.db import migrations


TASKS = ("talent_answer_plan", "talent_answer_judge")
OLD_PROVIDER = "greennode"
OLD_MODEL = "qwen/qwen3.6-flash"
NEW_PROVIDER = "gemini"
NEW_MODEL = "gemini-3.5-flash"
MARKER = "migration 0019"


def forward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    Route.objects.filter(
        task__in=TASKS,
        provider=OLD_PROVIDER,
        model=OLD_MODEL,
        updated_by__startswith="migration ",
    ).update(provider=NEW_PROVIDER, model=NEW_MODEL, updated_by=MARKER)


def backward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    Route.objects.filter(task__in=TASKS, updated_by=MARKER).update(
        provider=OLD_PROVIDER, model=OLD_MODEL, updated_by="migration 0012")


class Migration(migrations.Migration):
    dependencies = [("ai", "0018_answer_run_claim")]
    operations = [migrations.RunPython(forward, backward)]
