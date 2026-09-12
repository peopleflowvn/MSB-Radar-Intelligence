# -*- coding: utf-8 -*-
"""Worker trích xuất — claim job theo batch nhỏ, lease/retry/safe-stop (§21.3).

    python manage.py run_extraction_worker --once            # xử lý hết rồi thoát
    python manage.py run_extraction_worker --batch 5         # vòng lặp liên tục
    python manage.py run_extraction_worker --stop-file /tmp/stop-extraction

Dừng an toàn: tạo file ở `--stop-file` (mặc định `intel_worker.stop` cạnh
manage.py) — worker xong job hiện tại rồi thoát.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from intel.queue import run_worker


class Command(BaseCommand):
    help = "Chạy worker xử lý ExtractionJob."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=10)
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--no-ai-fallback", action="store_true",
                            help="Bỏ qua job use_ai nếu chưa cấu hình provider")
        parser.add_argument("--stop-file", default="")

    def handle(self, *args, **opts):
        stop_file = opts["stop_file"] or str(Path(settings.BASE_DIR) / "intel_worker.stop")

        def progress(job, totals):
            self.stdout.write(
                f"  job {job.pk} person={job.person_id} -> {job.status}  "
                f"[done={totals['done']} failed={totals['failed']} requeued={totals['requeued']}]")

        totals = run_worker(batch_size=opts["batch"], once=opts["once"],
                            stop_file=stop_file, on_progress=progress)
        self.stdout.write(self.style.SUCCESS(
            f"Xong: done={totals['done']} failed={totals['failed']} requeued={totals['requeued']}"))
