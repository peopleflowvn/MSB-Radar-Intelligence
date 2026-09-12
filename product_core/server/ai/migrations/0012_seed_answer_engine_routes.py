# -*- coding: utf-8 -*-
"""Ghim model cho ba chặng LLM của Answer Engine.

Ba chặng có ba đòi hỏi khác nhau, dùng chung một model là lãng phí ở đầu này và
thiếu chất lượng ở đầu kia:

    ① lập kế hoạch  gọi mỗi lượt, chỉ trả JSON ngắn  → cần NHANH   (qwen3.6-flash)
    ③ đọc & phán đoán  nuốt ~40 hồ sơ mỗi lượt        → cần RẺ mà đọc dài
    ⑤ viết câu trả lời  thứ người dùng thật sự đọc     → cần HAY NHẤT (v4-pro)

Chỉ tạo route còn thiếu — người vận hành đã chỉnh trên `/settings` thì giữ nguyên
lựa chọn của họ. Xoá route đi cũng không sao: router lùi về model mặc định của
nhà cung cấp.
"""
from django.db import migrations

#: ③ cố ý KHÔNG dùng `deepseek/*`: `providers.py` bỏ `reasoning_effort` cho các
#: model đó, nên chúng nghĩ hết hạn mức token và trả JSON cụt (xem migration 0013).
ROUTES = [
    ("talent_answer_plan", "greennode", "qwen/qwen3.6-flash"),
    ("talent_answer_judge", "greennode", "qwen/qwen3.6-flash"),
    ("talent_answer_compose", "greennode", "deepseek/deepseek-v4-pro"),
]


def seed(apps, schema_editor):
    TaskModelRoute = apps.get_model("ai", "TaskModelRoute")
    for task, provider, model in ROUTES:
        TaskModelRoute.objects.get_or_create(
            task=task,
            defaults={"provider": provider, "model": model,
                      "updated_by": "migration 0012"})


def unseed(apps, schema_editor):
    TaskModelRoute = apps.get_model("ai", "TaskModelRoute")
    TaskModelRoute.objects.filter(
        task__in=[task for task, _p, _m in ROUTES],
        updated_by="migration 0012").delete()


class Migration(migrations.Migration):

    dependencies = [("ai", "0011_taskmodelroute")]

    operations = [migrations.RunPython(seed, unseed)]
