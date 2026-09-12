# -*- coding: utf-8 -*-
"""Chuyển ③ (đọc & phán đoán) sang model KHÔNG có bước suy nghĩ.

Đo trên kho thật: `deepseek/deepseek-v4-flash` là model có bước suy nghĩ, và
`providers.py` cố tình bỏ `reasoning_effort` cho mọi model `deepseek/*` (chúng
trả HTTP 400 khi thấy tham số này). Hệ quả: ③ nghĩ hết sạch 3500 token trước khi
kịp mở ngoặc JSON, câu trả lời bị cắt, parse ra rỗng — rồi ⑤ đi báo với người
dùng "kho không có ai" trong khi ② đã tìm được 40 hồ sơ.

`qwen/qwen3.6-flash` tôn trọng `reasoning_effort="none"`, nên toàn bộ hạn mức
token dành cho JSON. Nó cũng là model nhanh nhất đo được (0.7s/lượt parse ngắn),
và ③ là chặng gọi nhiều lượt nhất trong cả luồng.

Chỉ sửa route do migration 0012 tạo — người vận hành đã tự chọn model khác trên
`/settings` thì giữ nguyên lựa chọn của họ.
"""
from django.db import migrations

TASK = "talent_answer_judge"
OLD = "deepseek/deepseek-v4-flash"
NEW = "qwen/qwen3.6-flash"


def forwards(apps, schema_editor):
    TaskModelRoute = apps.get_model("ai", "TaskModelRoute")
    TaskModelRoute.objects.filter(task=TASK, model=OLD).update(
        model=NEW, updated_by="migration 0013")


def backwards(apps, schema_editor):
    TaskModelRoute = apps.get_model("ai", "TaskModelRoute")
    TaskModelRoute.objects.filter(task=TASK, model=NEW).update(
        model=OLD, updated_by="migration 0013 (revert)")


class Migration(migrations.Migration):

    dependencies = [("ai", "0012_seed_answer_engine_routes")]

    operations = [migrations.RunPython(forwards, backwards)]
