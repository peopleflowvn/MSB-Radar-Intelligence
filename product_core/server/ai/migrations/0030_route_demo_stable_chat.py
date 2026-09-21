# -*- coding: utf-8 -*-
"""GLM cho ba tác vụ trợ lý chung — qwen bị chặn khi bắn liền nhau trong 1 lượt.

`talent/answer/chat.py::stream_chat` gọi `assistant_intent` rồi `assistant_web`
rồi `assistant_conversation` gần như CÙNG LÚC trong một lượt hội thoại. Cả ba
route trong CSDL đều đang trỏ `qwen/qwen3.6-flash` (migration 0014/0015/0024).
Đo trên production 21/09, giữa lúc thi: ba lượt gọi liền nhau chạm hạn mức theo
model, Gemini dự phòng thì HTTP 402 hết tiền — người dùng nhận
"Tôi chưa tra được câu này" cho một câu hỏi hoàn toàn bình thường
("msb có sản phẩm gì"). Ban tổ chức cũng khuyến nghị rời khỏi qwen khi hạ tầng
dùng chung bị nhiều đội cùng gọi cuối giai đoạn thi.

Không đổi `assistant_agent`/`assistant_outreach`/`assistant_estimate_reasoning`:
chưa đo được lượt nào của chúng thất bại, và đổi mà không có bằng chứng là lặp
lại đúng lỗi đã sửa (đoán thay vì đo).
"""
from django.db import migrations

MARKER = "migration 0030"
NEW = ("greennode", "z-ai/glm-5.2-hackathon")
TASKS = {
    "assistant_conversation": ("greennode", "qwen/qwen3.6-flash"),
    "assistant_intent": ("greennode", "qwen/qwen3.6-flash"),
    "assistant_web": ("greennode", "qwen/qwen3.6-flash"),
}


def _managed(value):
    value = str(value or "")
    return not value or value.startswith("migration") or value.startswith("benchmark")


def forward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    for task, old in TASKS.items():
        for route in Route.objects.filter(task=task):
            if _managed(route.updated_by) and (route.provider, route.model) in (old, NEW):
                route.provider, route.model = NEW
                route.updated_by = MARKER
                route.save(update_fields=["provider", "model", "updated_by"])


def backward(apps, schema_editor):
    Route = apps.get_model("ai", "TaskModelRoute")
    for task, old in TASKS.items():
        Route.objects.filter(task=task, updated_by=MARKER).update(
            provider=old[0], model=old[1], updated_by="migration (rollback 0030)")


class Migration(migrations.Migration):
    dependencies = [("ai", "0029_route_demo_stable_judge")]
    operations = [migrations.RunPython(forward, backward)]
