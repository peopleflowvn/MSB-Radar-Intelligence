# -*- coding: utf-8 -*-
"""Dựng lại chỉ mục bằng chứng khách hàng (text + full-text; vector chạy riêng).

    python manage.py rebuild_prospect_evidence_index
    python manage.py rebuild_prospect_evidence_index --person 123
    python manage.py rebuild_prospect_evidence_index --stop-file /tmp/stop

Chỉ quét người CÓ bằng chứng bán lẻ (hồ sơ RB, tín hiệu RB, bài đăng đã gắn
người). Quét toàn bộ `Person` là quét cả kho ứng viên — hàng trăm nghìn người
không có gì để lập chỉ mục ở đây. Người đã gộp vẫn được quét để dọn hàng cũ.
"""
import os
import time

from django.core.management.base import BaseCommand
from django.db.models import Q


class Command(BaseCommand):
    help = "Dựng lại ProspectEvidenceChunk từ các bảng nguồn."

    def add_arguments(self, parser):
        parser.add_argument("--person", type=int, default=0)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--stop-file", default="")

    def handle(self, *args, **options):
        from people.models import Person, Signal

        from rb.evidence_index import index_person
        from rb.models import ProspectEvidenceChunk

        if options["person"]:
            ids = [options["person"]]
        else:
            ids = list(Person.objects.filter(
                Q(rb_profile__isnull=False)
                | Q(signals__domain=Signal.DOMAIN_RB)
                | Q(social_posts__isnull=False)
                | Q(pk__in=ProspectEvidenceChunk.objects.values("person_id"))
            ).distinct().order_by("pk").values_list("pk", flat=True))
        if options["limit"]:
            ids = ids[:options["limit"]]

        from rb.evidence_index import mark_backfilled

        full_run = not options["person"] and not options["limit"]
        stopped = False
        started, written, failed = time.time(), 0, 0
        self.stdout.write(f"Bắt đầu: {len(ids)} người")
        for index, person_id in enumerate(ids, 1):
            if options["stop_file"] and os.path.exists(options["stop_file"]):
                self.stdout.write(self.style.WARNING("Gặp cờ dừng — dừng an toàn."))
                stopped = True
                break
            try:
                written += index_person(person_id)
            except Exception as exc:               # noqa: BLE001
                failed += 1
                self.stderr.write(f"person {person_id}: {exc}")
            if index % 500 == 0:
                self.stdout.write(f"  {index}/{len(ids)} · ghi {written} mẩu · lỗi {failed}")
        if full_run and not stopped and not failed:
            # Chỉ lúc này ② mới chuyển sang dùng chỉ mục — xem `evidence_index.populated`.
            mark_backfilled()
            self.stdout.write("Đã đánh dấu chỉ mục đầy đủ: truy hồi dùng full-text có chỉ mục.")
        elif full_run:
            self.stdout.write(self.style.WARNING(
                "Chưa đánh dấu đầy đủ (dừng giữa chừng hoặc có lỗi) — truy hồi vẫn "
                "dùng đường cũ. Chạy lại lệnh này."))
        self.stdout.write(self.style.SUCCESS(
            f"Xong: ghi {written} mẩu, {failed} lỗi, {time.time() - started:.0f}s. "
            "Tiếp theo: embed_prospect_evidence."))
