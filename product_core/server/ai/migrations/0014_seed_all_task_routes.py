# -*- coding: utf-8 -*-
"""Gieo route cho ĐỦ 22 tác vụ — bỏ tầng "thừa hưởng" vô hình.

Trước migration này chỉ 4 tác vụ có route trong CSDL và 4 cái lấy model từ env;
**13 cái còn lại im lặng rơi xuống `MSB_AI_GREENNODE_MODEL`**. Không ai chọn model
ấy cho chúng — đó chỉ là cái rơi xuống, và nó rơi trúng ba quả mìn (xem
`ai/tasks.py::DEFAULT_ROUTE`).

Migration này **không đè lên lựa chọn của người vận hành**: hàng nào đã có trong
`TaskModelRoute` thì giữ nguyên, chỉ tạo hàng còn thiếu. Người ta đã cân nhắc khi
đặt `talent_answer_compose` thành deepseek-v4-pro; không được xoá đi.
"""
from django.db import migrations

from ai.tasks import DEFAULT_ROUTE


def gieo(apps, schema_editor):
    TaskModelRoute = apps.get_model("ai", "TaskModelRoute")
    da_co = set(TaskModelRoute.objects.values_list("task", flat=True))
    TaskModelRoute.objects.bulk_create([
        TaskModelRoute(task=task, provider=provider, model=model, enabled=True,
                       updated_by="migration 0014")
        for task, (provider, model) in DEFAULT_ROUTE.items() if task not in da_co
    ])


def go(apps, schema_editor):
    """Chỉ gỡ đúng những hàng migration này tạo ra."""
    apps.get_model("ai", "TaskModelRoute").objects.filter(
        updated_by="migration 0014").delete()


class Migration(migrations.Migration):
    dependencies = [("ai", "0013_answer_judge_nonthinking_model")]
    operations = [migrations.RunPython(gieo, go)]
