# -*- coding: utf-8 -*-
"""Backfill có kiểm soát cho pipeline trích xuất (Master Plan §15 GĐ6, §21.6).

    python manage.py backfill_extraction --limit 50 --dry-run
    python manage.py backfill_extraction --limit 500 --stop-file stop.txt

Chạy 50 rồi 500 rồi mới toàn kho (§15 GĐ3). KHÔNG bật auto-accept mới, KHÔNG
deploy — chỉ chạy pipeline hiện có và báo cáo. Cổng dừng:

    error rate per-item > 5%   |  false-overwrite curated > 0

→ dừng ngay, in cảnh báo. (Ngưỡng khác — fallback provider, p95 latency — theo
dõi ở dashboard, ngoài phạm vi lệnh này.)
"""
import json
import os
import time

from django.core.management.base import BaseCommand

from intel.extraction import coverage_summary, run_for_person
from intel.models import ExtractedFact, ExtractionRun
from people.models import Person

ERROR_RATE_STOP = 0.05


class Command(BaseCommand):
    help = "Backfill trích xuất theo lô, có safe-stop + báo cáo coverage."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-ai", action="store_true")
        parser.add_argument("--stop-file", default="")
        parser.add_argument("--json", action="store_true", help="Chỉ in JSON tổng hợp")

    def handle(self, *args, **opts):
        qs = (Person.objects
              .filter(merged_into__isnull=True, source_records__isnull=False)
              .distinct().order_by("pk"))
        people = list(qs[opts["offset"]:opts["offset"] + opts["limit"]])
        if not people:
            self.stdout.write("Không có Person nào trong khoảng đã chọn.")
            return

        runs, errors, false_overwrites = [], 0, 0
        started = time.time()
        for i, person in enumerate(people, 1):
            if opts["stop_file"] and os.path.exists(opts["stop_file"]):
                self.stdout.write(self.style.WARNING(f"Thấy stop-file — dừng sau {i - 1} hồ sơ."))
                break
            run = run_for_person(person, dry_run=opts["dry_run"], use_ai=not opts["no_ai"])
            runs.append(run)
            if run.status == ExtractionRun.STATUS_FAILED:
                errors += 1
            false_overwrites += person.facts.filter(
                run=run, source_kind=ExtractedFact.SOURCE_AI,
                status=ExtractedFact.STATUS_ACCEPTED,
                field__in=_curated(person)).count()

            if not opts["json"] and i % 10 == 0:
                self.stdout.write(f"  {i}/{len(people)}…")

            rate = errors / i
            if rate > ERROR_RATE_STOP and i >= 20:
                self.stderr.write(self.style.ERROR(
                    f"DỪNG: error rate {rate:.0%} > {ERROR_RATE_STOP:.0%} sau {i} hồ sơ."))
                break
            if false_overwrites:
                self.stderr.write(self.style.ERROR(
                    f"DỪNG: {false_overwrites} fact AI accepted đè lên field curated."))
                break

        summary = {
            "processed": len(runs),
            "errors": errors,
            "error_rate": round(errors / len(runs), 3) if runs else 0,
            "false_overwrite_curated": false_overwrites,
            "elapsed_seconds": round(time.time() - started, 1),
            "dry_run": opts["dry_run"],
            "coverage": coverage_summary(runs),
        }
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        gate_ok = summary["error_rate"] <= ERROR_RATE_STOP and false_overwrites == 0
        self.stdout.write(
            self.style.SUCCESS("GATE OK") if gate_ok
            else self.style.ERROR("GATE FAIL — xem cảnh báo ở trên"))


def _curated(person):
    talent = getattr(person, "talent_profile", None)
    return set(getattr(talent, "curated_fields", []) or [])
