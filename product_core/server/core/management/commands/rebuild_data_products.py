# -*- coding: utf-8 -*-
"""Rebuild every derived/search product from durable raw records and CV text.

Safe to resume: use --after-id with the last printed Person id. Embedding stays
in its own worker so this command never waits for or overloads an external API.
"""
from django.core.management.base import BaseCommand

from people.models import Person


class Command(BaseCommand):
    help = "Tái chiếu raw/fact/CV thành profile và các chỉ mục tìm kiếm."

    def add_arguments(self, parser):
        parser.add_argument("--after-id", type=int, default=0)
        parser.add_argument("--limit", type=int, default=1000)
        parser.add_argument("--enqueue-ai", action="store_true")

    def handle(self, *args, **options):
        from intel.queue import enqueue
        from talent.derive import apply_extracted_facts, derive
        from talent.semantic_index import index_person as semantic_index_person
        from talent.vector_index import index_person as vector_index_person

        rows = (Person.applicants().filter(pk__gt=max(0, options["after_id"]))
                .order_by("pk").values_list("pk", flat=True)[:max(1, options["limit"])])
        done = failed = queued = 0
        last_id = options["after_id"]
        for person_id in rows.iterator(chunk_size=100):
            last_id = person_id
            try:
                person = Person.objects.get(pk=person_id)
                derive(person)
                apply_extracted_facts(person)
                semantic_index_person(person_id)
                vector_index_person(person_id, with_embeddings=False)
                if options["enqueue_ai"]:
                    enqueue(person, batch="data-rebuild")
                    queued += 1
                done += 1
            except Exception as exc:                 # one bad profile must not stop corpus
                failed += 1
                self.stderr.write(f"Person {person_id}: {str(exc)[:240]}")
        self.stdout.write(self.style.SUCCESS(
            f"Xong {done}; lỗi {failed}; enqueue AI {queued}; last_id={last_id}."))
