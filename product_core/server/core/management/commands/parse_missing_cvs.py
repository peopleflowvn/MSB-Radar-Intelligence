# -*- coding: utf-8 -*-
import time

from django.core.management.base import BaseCommand
from django.db.models import Q
from people.models import Document

from core.cv_parsing import parse_missing_document
from core.document_preview import prepare_preview


class Command(BaseCommand):
    help = "Parsing bù trên Hub cho CV có file gốc nhưng chưa có parsed text."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--retry-failed", action="store_true")
        parser.add_argument("--loop", action="store_true",
                            help="Chạy như worker nền, quét lại theo --interval giây.")
        parser.add_argument("--interval", type=int, default=20)

    def handle(self, *args, **options):
        while True:
            self._run_once(options)
            if not options["loop"]:
                return
            time.sleep(max(5, options["interval"]))

    def _run_once(self, options):
        missing = Q(primary_text_version__isnull=True, parsed_text="")
        retryable_ai = Q(parse_provider="hub") & ~Q(parse_error="")
        preview_pending = Q(preview_status=Document.PARSE_PENDING) | Q(preview_status="")
        retryable_preview = Q(preview_status=Document.PARSE_FAILED)
        query = Document.objects.exclude(storage_key="").filter(
            missing | preview_pending |
            ((retryable_ai | retryable_preview) if options["retry_failed"] else Q(pk__in=[])))
        if not options["retry_failed"]:
            query = query.filter(
                Q(parse_status=Document.PARSE_PENDING) | Q(parse_status="") | preview_pending)
        rows = list(query.order_by("created_at")[:max(1, options["limit"])])
        done = failed = 0
        for document in rows:
            prepare_preview(document)
            result = parse_missing_document(document)
            if result.primary_text_version_id:
                done += 1
            else:
                failed += 1
        if rows:
            self.stdout.write(self.style.SUCCESS(
                f"Đã xử lý {len(rows)} CV: {done} có text, {failed} chưa đọc được."))
