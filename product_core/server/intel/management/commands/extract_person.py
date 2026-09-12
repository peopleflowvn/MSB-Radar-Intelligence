# -*- coding: utf-8 -*-
"""Chạy trích xuất fact cho một Person hoặc một batch nhỏ (Master Plan §7, §21.6).

    python manage.py extract_person --person 123
    python manage.py extract_person --person 123 --dry-run --no-ai
    python manage.py extract_person --limit 50            # 50 Person đầu có SourceRecord

Không đi qua hàng đợi — dùng để phát triển/soi. Backfill thật dùng
`run_extraction_worker` + `backfill_extraction`.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from intel.extraction import coverage_summary, run_for_person
from people.models import Person


class Command(BaseCommand):
    help = "Trích xuất fact/provenance cho Person (trực tiếp, không qua queue)."

    def add_arguments(self, parser):
        parser.add_argument("--person", type=int, default=None)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-ai", action="store_true", help="Bỏ bước AI-fill-gaps")

    def handle(self, *args, **opts):
        use_ai = not opts["no_ai"]
        dry = opts["dry_run"]

        if opts["person"]:
            people = Person.objects.filter(pk=opts["person"])
            if not people:
                raise CommandError(f"Không thấy Person {opts['person']}")
        else:
            qs = (Person.objects
                  .filter(merged_into__isnull=True, source_records__isnull=False)
                  .distinct().order_by("pk"))
            people = qs[:opts["limit"]] if opts["limit"] else qs
            if not opts["limit"]:
                raise CommandError("Cần --person hoặc --limit N.")

        runs = []
        for person in people:
            run = run_for_person(person, dry_run=dry, use_ai=use_ai)
            runs.append(run)
            self.stdout.write(
                f"  Person {person.pk}: {run.status} · " + json.dumps(run.coverage, ensure_ascii=False))

        self.stdout.write(self.style.SUCCESS(
            f"\n{len(runs)} run. Tổng hợp coverage:\n"
            + json.dumps(coverage_summary(runs), ensure_ascii=False, indent=2)))
