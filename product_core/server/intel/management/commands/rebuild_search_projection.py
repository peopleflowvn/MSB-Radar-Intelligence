# -*- coding: utf-8 -*-
"""Dựng lại Materialized Search Projection từ fact đã accepted (Master Plan §21.7).

    python manage.py rebuild_search_projection
    python manage.py rebuild_search_projection --person 123
    python manage.py rebuild_search_projection --limit 500
"""
from django.core.management.base import BaseCommand

from intel.projection import PROJECTION_VERSION, build_for_person, rebuild_all
from people.models import Person


class Command(BaseCommand):
    help = "Materialize fact accepted -> MaterializedProfile (có version)."

    def add_arguments(self, parser):
        parser.add_argument("--person", type=int, default=None)
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **opts):
        if opts["person"]:
            person = Person.objects.get(pk=opts["person"])
            proj = build_for_person(person)
            self.stdout.write(self.style.SUCCESS(
                f"Person {person.pk}: {proj.fact_count} fact, v{proj.projection_version}"))
            return
        stats = rebuild_all(limit=opts["limit"],
                            on_progress=lambda n: self.stdout.write(f"  {n}…"))
        self.stdout.write(self.style.SUCCESS(
            f"Đã dựng {stats['built']} ảnh (projection v{PROJECTION_VERSION})."))
