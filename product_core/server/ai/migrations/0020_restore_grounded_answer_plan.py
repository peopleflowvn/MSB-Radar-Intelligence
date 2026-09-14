# -*- coding: utf-8 -*-
"""Khôi phục Qwen cho plan sau khi probe production cho thấy mất recall.

Gemini Flash vẫn chấm các lô hồ sơ nhanh; bước hiểu câu hỏi dùng lại Qwen vì
probe cùng truy vấn production cho kết quả grounded ổn định hơn.
"""
from django.db import migrations


TASK = "talent_answer_plan"
MARKER = "migration 0020"


def forward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    Route.objects.filter(task=TASK, updated_by="migration 0019").update(
        provider="greennode", model="qwen/qwen3.6-flash", updated_by=MARKER)


def backward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    Route.objects.filter(task=TASK, updated_by=MARKER).update(
        provider="gemini", model="gemini-3.5-flash", updated_by="migration 0019")


class Migration(migrations.Migration):
    dependencies = [("ai", "0019_route_fast_answer_stages")]
    operations = [migrations.RunPython(forward, backward)]
