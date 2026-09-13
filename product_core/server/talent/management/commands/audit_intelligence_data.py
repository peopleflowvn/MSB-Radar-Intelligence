"""Report non-PII Product Core counts used to reconcile the V2 RAG index."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q

from core.models import SourceRecord
from people.models import Document, Person
from talent.models import IntelligenceDocumentTombstone, TalentProfile


class Command(BaseCommand):
    help = "Emit non-PII data counts for Intelligence V2 reconciliation."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        eligible_documents = Document.objects.filter(
            person__merged_into__isnull=True,
            person__is_applicant=True,
            parse_status=Document.PARSE_DONE,
        ).filter(
            Q(primary_text_version__text__gt="")
            | Q(primary_text_version__isnull=True, parsed_text__gt="")
        )
        user_model = get_user_model()
        payload = {
            "users": {
                "total": user_model.objects.count(),
                "active": user_model.objects.filter(is_active=True).count(),
                "staff": user_model.objects.filter(is_staff=True).count(),
            },
            "people": {
                "total": Person.objects.count(),
                "applicants": Person.objects.filter(is_applicant=True).count(),
                "active_applicants": Person.applicants().count(),
                "merged": Person.objects.filter(merged_into__isnull=False).count(),
            },
            "documents": {
                "total": Document.objects.count(),
                "parsed": Document.objects.filter(parse_status=Document.PARSE_DONE).count(),
                "with_storage_key": Document.objects.exclude(storage_key="").count(),
                "eligible_for_intelligence": eligible_documents.count(),
            },
            "source_records": {
                "total": SourceRecord.objects.count(),
                "resolved": SourceRecord.objects.filter(status=SourceRecord.STATUS_RESOLVED).count(),
                "pending": SourceRecord.objects.filter(status=SourceRecord.STATUS_PENDING).count(),
            },
            "talent_profiles": TalentProfile.objects.count(),
            "intelligence_tombstones": IntelligenceDocumentTombstone.objects.count(),
        }
        rendered = json.dumps(payload, sort_keys=True)
        if options["as_json"]:
            self.stdout.write(rendered)
        else:
            self.stdout.write(json.dumps(payload, indent=2, sort_keys=True))
