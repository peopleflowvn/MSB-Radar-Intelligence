# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

from people.models import Person
from talent.search_v2 import build_dossier


class Command(BaseCommand):
    help = "Idempotently backfill typed SearchProjection and BaseDossier."

    def add_arguments(self, parser):
        parser.add_argument("--after-id", type=int, default=0)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--batch-size", type=int, default=1000)

    def handle(self, *args, **options):
        queryset = (Person.applicants().filter(pk__gt=options["after_id"])
                    .order_by("pk").values_list("pk", flat=True))
        if options["limit"]:
            queryset = queryset[:options["limit"]]
        done, failed, last_id = 0, 0, options["after_id"]
        for person_id in queryset.iterator(chunk_size=max(1, options["batch_size"])):
            last_id = person_id
            try:
                build_dossier(person_id)
                done += 1
            except Exception as exc:  # one corrupt dossier must not lose the checkpoint
                failed += 1
                self.stderr.write(f"person={person_id}: {exc}")
        self.stdout.write(self.style.SUCCESS(
            f"built={done} failed={failed} last_id={last_id}"))
