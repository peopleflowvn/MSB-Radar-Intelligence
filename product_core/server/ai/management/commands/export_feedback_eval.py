# -*- coding: utf-8 -*-
"""Xuất 👍/👎 thành tập eval ẩn danh (Master Plan §11.3, §15 GĐ5).

    python manage.py export_feedback_eval --out docs/benchmark/feedback_eval/<UTC>.jsonl

"Dùng 👍/👎 và lý do để xây benchmark TRƯỚC" — không fine-tune tự động. Bản xuất
này loại định danh người dùng và redact email/điện thoại rõ ràng.
"""
import json
import re
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from ai.models import AssistantFeedback

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)\d{8,10}(?!\d)")


def _redact(text):
    text = _EMAIL.sub("[email]", str(text or ""))
    return _PHONE.sub("[phone]", text)


class Command(BaseCommand):
    help = "Xuất phản hồi trợ lý thành JSONL ẩn danh cho benchmark/eval."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="")
        parser.add_argument("--rating", choices=["up", "down"], default=None)

    def handle(self, *args, **opts):
        rows = AssistantFeedback.objects.all().order_by("created_at")
        if opts["rating"]:
            rows = rows.filter(rating=opts["rating"])

        stamp = f"{datetime.now(dt_timezone.utc):%Y%m%dT%H%M%SZ}"
        out_path = Path(opts["out"]) if opts["out"] else (
            Path(settings.BASE_DIR).parent / "docs" / "benchmark" / "feedback_eval"
            / f"{stamp}.jsonl")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        n = 0
        with out_path.open("w", encoding="utf-8") as fh:
            for i, fb in enumerate(rows.iterator(), 1):
                fh.write(json.dumps({
                    "id": f"fb{i}",
                    "surface": fb.surface,
                    "rating": fb.rating,
                    "reason": _redact(fb.reason),
                    "question": _redact(fb.question)[:2000],
                    "answer": _redact(fb.answer)[:4000],
                    "at": fb.created_at.date().isoformat(),
                }, ensure_ascii=False) + "\n")
                n += 1

        self.stdout.write(self.style.SUCCESS(f"Đã xuất {n} phản hồi → {out_path}"))
