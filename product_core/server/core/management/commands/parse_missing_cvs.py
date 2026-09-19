# -*- coding: utf-8 -*-
import time

from django.core.management.base import BaseCommand
from people.models import Document

from core.cv_parsing import needs_parsing, parse_due_documents


class Command(BaseCommand):
    help = ("Parsing bù trên Hub cho CV có file gốc nhưng chưa có text dùng được "
            "(chưa có text, text hỏng/trang bìa, OCR lỗi). Cùng hàng đợi với worker nền.")

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--retry-failed", action="store_true",
                            help="Mở lại cả file đã chốt `unreadable` và bỏ lịch chờ thử lại.")
        parser.add_argument("--loop", action="store_true",
                            help="Chạy như worker nền, quét lại theo --interval giây.")
        parser.add_argument("--interval", type=int, default=20)

    def handle(self, *args, **options):
        if options["retry_failed"]:
            reopened = (Document.objects.exclude(storage_key="")
                        .filter(parse_status__in=[Document.PARSE_UNREADABLE,
                                                  Document.PARSE_FAILED])
                        .update(parse_status=Document.PARSE_FAILED, parse_attempts=0,
                                next_parse_at=None))
            self.stdout.write(f"Mở lại {reopened} CV lỗi/không đọc được.")
        while True:
            handled = parse_due_documents(max(1, options["limit"]))
            waiting = needs_parsing().count()
            if handled or not options["loop"]:
                self.stdout.write(self.style.SUCCESS(
                    f"Đã xử lý {handled} CV. Còn {waiting} CV chưa có text dùng được "
                    f"(gồm cả CV đang chờ lượt thử lại)."))
            if not options["loop"]:
                return
            time.sleep(max(5, options["interval"]))
