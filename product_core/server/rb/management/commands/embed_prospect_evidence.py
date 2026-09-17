# -*- coding: utf-8 -*-
"""Worker nền tính embedding cho chỉ mục bằng chứng khách hàng.

Hàng đợi chính là bảng: mẩu nào `embedding_fingerprint != fingerprint` là vector
cũ hoặc chưa có. Chạy lại an toàn, dừng giữa chừng an toàn.

    python manage.py embed_prospect_evidence --limit 5000
    python manage.py embed_prospect_evidence --loop --stop-file /tmp/stop-embed
    python manage.py embed_prospect_evidence --then-pin

Dùng CÙNG model embedding với Talent (route `talent_embedding` trong /settings) —
xem docstring `rb/evidence_index.py` về vì sao phải là cùng một model.
"""
import os
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Tính embedding cho ProspectEvidenceChunk có vector đã cũ."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=1000,
                            help="Tối đa bao nhiêu mẩu lượt này (0 = không giới hạn).")
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--sleep", type=float, default=1.0)
        parser.add_argument("--stop-file", default="")
        parser.add_argument("--then-pin", action="store_true",
                            help="Hàng đợi rỗng ⇒ pin_vector_dimensions --apply.")

    def handle(self, *args, **options):
        from rb.evidence_index import embed_chunk, stale_chunks

        limit, batch = options["limit"], max(1, options["batch_size"])
        processed = failed = 0
        started = time.time()
        while True:
            if options["stop_file"] and os.path.exists(options["stop_file"]):
                self.stdout.write(self.style.WARNING("Gặp cờ dừng."))
                break
            budget = batch if limit <= 0 else min(batch, limit - processed - failed)
            if budget <= 0:
                break
            rows = list(stale_chunks(limit=budget))
            if not rows:
                self.stdout.write("Hàng đợi rỗng.")
                if options["then_pin"] and processed:
                    from django.core.management import call_command
                    try:
                        call_command("pin_vector_dimensions", "--apply")
                    except Exception as exc:       # noqa: BLE001
                        self.stderr.write(f"pin_vector_dimensions lỗi: {exc}")
                if options["loop"]:
                    time.sleep(max(5.0, options["sleep"]))
                    continue
                break
            batch_ok = 0
            for row in rows:
                if embed_chunk(row):
                    processed += 1
                    batch_ok += 1
                else:
                    failed += 1
            self.stdout.write(f"  +{len(rows)} · xong {processed} · lỗi {failed}")
            if batch_ok == 0:
                # Cả lô hỏng: provider chết hoặc chưa cấu hình. Không quay vòng đốt
                # CPU trên cùng một lô mãi — lô này sẽ còn nằm trong hàng đợi.
                self.stderr.write(self.style.ERROR(
                    "Không embed được mẩu nào — kiểm tra route `talent_embedding` "
                    "trong /settings (provider bật, có khoá, có mã model)."))
                if options["loop"]:
                    time.sleep(max(60.0, options["sleep"]))
                    continue
                break
            time.sleep(max(0.0, options["sleep"]) if options["loop"] else 0)
        self.stdout.write(self.style.SUCCESS(
            f"Xong: {processed} vector mới, {failed} lỗi, {time.time() - started:.0f}s."))
