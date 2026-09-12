# -*- coding: utf-8 -*-
"""`assistant_conversation` → qwen3.6-flash: model cũ nuốt `reasoning_effort`.

Cùng lớp lỗi migration 0015 sửa cho 5 tác vụ soạn thư. `ai/conversation.py::
build_conversation_request` nay truyền `reasoning_effort="none"` (hạn mức chỉ
600 token, câu hội thoại không cần model "nghĩ"), nhưng `deepseek-v4-flash` bị
`ai/providers.py` cắt bỏ tham số đó — nên model vẫn nghĩ, ăn hết 600 token, và
stream đứt giữa chừng. Đúng cái ảnh test 04/09 cho thấy: "Bạn tự đánh giá khả
năng của mình thế nào" → "Mất kết nối khi đang trả lời".

Chỉ sửa hàng do migration 0014/0015 tạo và chưa ai đụng vào.
"""
from django.db import migrations

CU = ("deepseek/deepseek-v4-flash",)
MOI = "qwen/qwen3.6-flash"
DAU = ("migration 0014", "migration 0015")


def sua(apps, schema_editor):
    TaskModelRoute = apps.get_model("ai", "TaskModelRoute")
    TaskModelRoute.objects.filter(
        task="assistant_conversation", model__in=CU, updated_by__in=DAU).update(
            model=MOI, provider="greennode", updated_by="migration 0016")


def lui(apps, schema_editor):
    TaskModelRoute = apps.get_model("ai", "TaskModelRoute")
    TaskModelRoute.objects.filter(
        task="assistant_conversation", updated_by="migration 0016").update(
            model="deepseek/deepseek-v4-flash", updated_by="migration 0015")


class Migration(migrations.Migration):
    dependencies = [("ai", "0015_sua_route_bi_cat_token")]
    operations = [migrations.RunPython(sua, lui)]
