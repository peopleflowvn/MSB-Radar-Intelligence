# -*- coding: utf-8 -*-
"""Đưa các chặng đã ghim Gemini về lại GreenNode làm nhà cung cấp chính.

Quyết định vận hành: GreenNode là hạ tầng chính — vừa là hạ tầng của ban tổ
chức, vừa là điều kiện tranh giải "Best Use of GreenNode AI Platform". Gemini
chỉ còn vai trò dự phòng khi GreenNode lỗi tạm thời, không còn là provider
chính cho bất kỳ tác vụ sinh văn bản nào (router vẫn tự chuyển sang Gemini nếu
GreenNode timeout/5xx — xem `ai/router.py::DEFAULT_ORDER`, gemini đứng ngay
sau greennode).

`talent_embedding` KHÔNG nằm trong migration này: GreenNode chưa phục vụ model
embedding nào (`ai/catalog.py::STATIC`), nên tác vụ đó bắt buộc ở lại Gemini.

Chỉ cập nhật route vẫn do migration quản lý (`updated_by` khớp đúng migration
đã đặt giá trị Gemini hiện tại); lựa chọn thủ công trong /settings không bị
ghi đè.
"""
from django.db import migrations


MARKER = "migration 0024"
GEMINI_PROVIDER, GEMINI_MODEL = "gemini", "gemini-3.5-flash"

# (task, model GreenNode mục tiêu, updated_by hiện tại cần khớp)
TARGETS = [
    ("talent_answer_plan", "qwen/qwen3.6-flash", "migration 0021"),
    ("talent_answer_judge", "qwen/qwen3.6-flash", "migration 0019"),
    ("talent_answer_compose", "deepseek/deepseek-v4-pro", "migration 0021"),
    ("assistant_conversation", "qwen/qwen3.6-flash", "migration 0021"),
]


def forward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    for task, model, prev_marker in TARGETS:
        Route.objects.filter(task=task, provider=GEMINI_PROVIDER, model=GEMINI_MODEL,
                             updated_by=prev_marker).update(
            provider="greennode", model=model, updated_by=MARKER)


def backward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    for task, _model, prev_marker in TARGETS:
        Route.objects.filter(task=task, updated_by=MARKER).update(
            provider=GEMINI_PROVIDER, model=GEMINI_MODEL, updated_by=prev_marker)


class Migration(migrations.Migration):
    dependencies = [("ai", "0023_route_rb_suggest_product_reasoning")]
    operations = [migrations.RunPython(forward, backward)]
