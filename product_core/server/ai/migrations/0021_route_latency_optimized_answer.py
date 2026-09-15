# -*- coding: utf-8 -*-
"""Chuyển các chặng tương tác sang Gemini Flash theo benchmark latency.

Chỉ cập nhật route vẫn do migration quản lý. Khoá/model do quản trị viên chọn
trong /settings không bị ghi đè. Retrieval, RBAC và citation verification vẫn
là các cổng độc lập, không giao cho model quyết định.
"""
from django.db import migrations


MODEL = "gemini-3.5-flash"
MARKER = "migration 0021"


def forward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    Route.objects.filter(task="talent_answer_plan", updated_by="migration 0020").update(
        provider="gemini", model=MODEL, updated_by=MARKER)
    Route.objects.filter(task="talent_answer_compose", provider="greennode",
                         model="deepseek/deepseek-v4-pro",
                         updated_by__startswith="migration ").update(
        provider="gemini", model=MODEL, updated_by=MARKER)
    Route.objects.filter(task="assistant_conversation", provider="greennode",
                         model="qwen/qwen3.6-flash",
                         updated_by__startswith="migration ").update(
        provider="gemini", model=MODEL, updated_by=MARKER)


def backward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    Route.objects.filter(task="talent_answer_plan", updated_by=MARKER).update(
        provider="greennode", model="qwen/qwen3.6-flash", updated_by="migration 0020")
    Route.objects.filter(task="talent_answer_compose", updated_by=MARKER).update(
        provider="greennode", model="deepseek/deepseek-v4-pro", updated_by="migration 0012")
    Route.objects.filter(task="assistant_conversation", updated_by=MARKER).update(
        provider="greennode", model="qwen/qwen3.6-flash", updated_by="migration 0016")


class Migration(migrations.Migration):
    dependencies = [("ai", "0020_restore_grounded_answer_plan")]
    operations = [migrations.RunPython(forward, backward)]
