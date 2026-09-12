# -*- coding: utf-8 -*-
"""Đưa Person vào hàng đợi trích xuất (Master Plan §21.3).

    python manage.py enqueue_extraction --all
    python manage.py enqueue_extraction --person 1 --person 2
    python manage.py enqueue_extraction --all --no-ai --batch nightly

Chỉ enqueue — không chạy. Worker: `run_extraction_worker`.
"""
from django.core.management.base import BaseCommand, CommandError

from intel.queue import enqueue_many
from people.models import Person


class Command(BaseCommand):
    help = "Enqueue ExtractionJob cho Person."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--person", type=int, action="append", default=[])
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--no-ai", action="store_true")
        parser.add_argument("--batch", default="manual")

    def handle(self, *args, **opts):
        if opts["all"]:
            ids = (Person.objects
                   .filter(merged_into__isnull=True, source_records__isnull=False)
                   .distinct().order_by("pk").values_list("pk", flat=True))
            if opts["limit"]:
                ids = ids[:opts["limit"]]
        elif opts["person"]:
            ids = opts["person"]
        else:
            raise CommandError("Cần --all hoặc --person.")

        created = enqueue_many(list(ids), use_ai=not opts["no_ai"], batch=opts["batch"])
        self.stdout.write(self.style.SUCCESS(
            f"Đã enqueue {created} job mới (batch={opts['batch']})."))
