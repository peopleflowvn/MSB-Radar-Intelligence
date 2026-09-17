# -*- coding: utf-8 -*-
"""Gieo route cho tác vụ mới `rb_suggest_product_reasoning`.

Không có hàng trong `TaskModelRoute` thì tác vụ im lặng rơi xuống model mặc
định của provider — đúng cái tầng "thừa hưởng vô hình" mà migration 0014 đã dọn.
Giữ nguyên lựa chọn của người vận hành nếu hàng đã tồn tại.
"""
from django.db import migrations

from ai.tasks import DEFAULT_ROUTE

TASK = "rb_suggest_product_reasoning"


def gieo(apps, schema_editor):
    TaskModelRoute = apps.get_model("ai", "TaskModelRoute")
    if TaskModelRoute.objects.filter(task=TASK).exists():
        return
    provider, model = DEFAULT_ROUTE[TASK]
    TaskModelRoute.objects.create(task=TASK, provider=provider, model=model,
                                  enabled=True, updated_by="migration 0023")


def go(apps, schema_editor):
    apps.get_model("ai", "TaskModelRoute").objects.filter(
        task=TASK, updated_by="migration 0023").delete()


class Migration(migrations.Migration):
    dependencies = [("ai", "0022_route_estimate_reasoning")]
    operations = [migrations.RunPython(gieo, go)]
