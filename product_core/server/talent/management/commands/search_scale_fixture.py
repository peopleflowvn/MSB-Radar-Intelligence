# -*- coding: utf-8 -*-
"""Generate reproducible synthetic search rows or benchmark existing fixtures."""
import random
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from people.models import Person
from talent.models import SearchProjection, TalentProfile
from talent.search_v2 import Constraint, RadarTurnPlan, compile_projection_query


class Command(BaseCommand):
    help = "Generate synthetic (never real PII) search fixtures and measure T0/count."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("generate", "benchmark"))
        parser.add_argument("--count", type=int, default=0)
        parser.add_argument("--seed", type=int, default=20260920)
        parser.add_argument("--batch-size", type=int, default=5000)
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if options["action"] == "generate":
            if not options["confirm"] or options["count"] <= 0:
                raise CommandError("generate requires --count N --confirm")
            self._generate(options["count"], options["seed"], options["batch_size"])
        self._benchmark()

    @transaction.atomic
    def _generate(self, count, seed, batch_size):
        rng = random.Random(seed)
        titles = ("data analyst", "python developer", "relationship manager", "accountant")
        locations = ("ha noi", "ho chi minh", "da nang")
        start = Person.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
        created = 0
        while created < count:
            size = min(batch_size, count - created)
            people = Person.objects.bulk_create([
                Person(display_name=f"SYNTH-{seed}-{created + i:07d}", is_applicant=True)
                for i in range(size)], batch_size=batch_size)
            profiles, projections = [], []
            for person in people:
                title, location = rng.choice(titles), rng.choice(locations)
                years = rng.randrange(0, 21)
                profiles.append(TalentProfile(person=person, current_title=title,
                                              location=location, years_experience=years))
                values = {"title_norm": title, "location_norm": location,
                          "years_experience": years, "skills_norm": ["sql", "python"]
                          if title == "data analyst" else [], "version": 1}
                projections.append(SearchProjection(
                    person=person, fingerprint=f"synthetic-{seed}-{person.pk}",
                    searchable_text=f"{title} {location}", **values))
            TalentProfile.objects.bulk_create(profiles, batch_size=batch_size)
            SearchProjection.objects.bulk_create(projections, batch_size=batch_size)
            created += size
            self.stdout.write(f"created={created}/{count}")
        self.stdout.write(self.style.SUCCESS(
            f"seed={seed} count={count} first_previous_id={start}"))

    def _benchmark(self):
        plan = RadarTurnPlan(must=[
            Constraint("title", "data analyst"),
            Constraint("location", "ha noi", kind="geo"),
            Constraint("years_experience", 3, kind="range", op="gte"),
        ])
        queryset, explain = compile_projection_query(plan)
        started = time.perf_counter()
        count = queryset.count()
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        payload = {"matched": count, "count_ms": elapsed_ms,
                   "rows": SearchProjection.objects.count(), "compiler": explain,
                   "db_vendor": connection.vendor}
        if connection.vendor == "postgresql":
            payload["explain"] = queryset.explain(analyze=True, buffers=True, format="json")
        self.stdout.write(str(payload))
