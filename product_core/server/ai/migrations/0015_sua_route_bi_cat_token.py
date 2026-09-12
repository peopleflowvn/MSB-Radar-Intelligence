# -*- coding: utf-8 -*-
"""Sửa 5 route mà migration 0014 gieo sai — model nuốt hết hạn mức token.

Migration 0014 gieo mặc định theo `kind`: việc cần hành văn thì cho model viết
tốt nhất. Đúng nguyên tắc, sai thực tế — vì nó bỏ qua **hạn mức token của chỗ
gọi**.

`ai/providers.py` cắt bỏ `reasoning_effort` cho mọi model `deepseek/*` (chúng
trả HTTP 400 với tham số đó). Nên lời dặn "đừng nghĩ" không tới được model; nó
vẫn nghĩ, và phần nghĩ ăn chung hạn mức với phần chữ. Đo thật trên production,
cùng một đề bài soạn thư:

    deepseek-v4-pro    @800  → 0 ký tự, RỖNG HOÀN TOÀN
    deepseek-v4-pro    @1200 → cụt giữa câu
    deepseek-v4-flash  @800  → cụt giữa chữ
    qwen3.6-flash      @800  → 909 ký tự, trọn vẹn, 2,9s

Năm tác vụ dưới đây có hạn mức 700–1200, tức nằm đúng vùng hỏng:

    assistant_outreach  700    talent_corpus_qa   900
    rb_outreach_draft   800    outreach_draft    1200
    assistant_web      1200

`talent_answer_compose` KHÔNG nằm trong danh sách: hạn mức 7000, rộng gấp gần
chín lần, và đã đo trọn vẹn trên production. Nó giữ `deepseek-v4-pro`.

**Chỉ sửa hàng do chính 0014 tạo ra và chưa ai đụng vào.** Người vận hành đã
cân nhắc rồi chọn khác thì đó là lựa chọn của họ — migration không được đè.
"""
from django.db import migrations

SUA = {
    "assistant_outreach": "qwen/qwen3.6-flash",
    "rb_outreach_draft": "qwen/qwen3.6-flash",
    "outreach_draft": "qwen/qwen3.6-flash",
    "talent_corpus_qa": "qwen/qwen3.6-flash",
    "assistant_web": "qwen/qwen3.6-flash",
}
DAU_0014 = "migration 0014"


def sua(apps, schema_editor):
    TaskModelRoute = apps.get_model("ai", "TaskModelRoute")
    for task, model in SUA.items():
        TaskModelRoute.objects.filter(
            task=task, updated_by=DAU_0014).update(
                model=model, provider="greennode", updated_by="migration 0015")


def lui(apps, schema_editor):
    """Trả về đúng giá trị 0014 đã đặt, không đoán."""
    TaskModelRoute = apps.get_model("ai", "TaskModelRoute")
    cu = {"assistant_outreach": "deepseek/deepseek-v4-pro",
          "rb_outreach_draft": "deepseek/deepseek-v4-pro",
          "outreach_draft": "deepseek/deepseek-v4-pro",
          "talent_corpus_qa": "deepseek/deepseek-v4-flash",
          "assistant_web": "deepseek/deepseek-v4-flash"}
    for task, model in cu.items():
        TaskModelRoute.objects.filter(
            task=task, updated_by="migration 0015").update(
                model=model, updated_by=DAU_0014)


class Migration(migrations.Migration):
    dependencies = [("ai", "0014_seed_all_task_routes")]
    operations = [migrations.RunPython(sua, lui)]
