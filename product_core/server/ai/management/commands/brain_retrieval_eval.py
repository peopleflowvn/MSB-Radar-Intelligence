"""Real SQLite fallback retrieval on an isolated synthetic corpus."""
import hashlib
import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from ai.brain_eval import gold_set, percentile, retrieval_metrics


class Command(BaseCommand):
    help = "Synthetic retrieval benchmark. Requires DATABASE_URL=sqlite:///:memory:."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True)

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        if db["ENGINE"] != "django.db.backends.sqlite3" or db["NAME"] != ":memory:":
            raise CommandError("Refusing to seed a persistent DB; use sqlite:///:memory:.")
        call_command("migrate", verbosity=0, interactive=False)
        from people.models import Document, Person
        from talent.answer.plan import QueryPlan
        from talent.answer.retrieve import retrieve
        from talent.models import CVChunk, PersonSearchDocument
        from talent.vector_index import fold_text
        gold = gold_set()
        for person in gold["people"]:
            p = Person.objects.create(pk=person["id"], display_name=person["name"])
            body = person["text"]
            digest = hashlib.sha256(body.encode()).hexdigest()
            doc = Document.objects.create(person=p, sha256=digest, parsed_text=body)
            PersonSearchDocument.objects.update_or_create(person=p, defaults={
                "fingerprint": digest, "content": person["name"] + " " + body,
                "content_norm": fold_text(person["name"] + " " + body)})
            CVChunk.objects.update_or_create(document=doc, ordinal=0, defaults={
                "person": p, "fingerprint": digest, "text": body, "text_norm": fold_text(body)})
        rows = []
        for case in gold["cases"]:
            if "queries" not in case or "expected_ids" not in case:
                continue
            started = time.perf_counter()
            found = retrieve(QueryPlan(search_queries=case["queries"]), pool=10)
            rows.append({"case": case["id"], "ids": [c.person_id for c in found],
                         **retrieval_metrics(case["expected_ids"], [c.person_id for c in found]),
                         "latency_ms": round((time.perf_counter() - started) * 1000, 3)})
        def mean(key):
            values = [r[key] for r in rows if r[key] is not None]
            return sum(values) / len(values) if values else None
        report = {"suite": "sqlite_fallback_retrieval", "gold_version": gold["version"],
                  "scope": "6 synthetic people, curated query expansions, K=10; NOT intent, dense retrieval, or production acceptance",
                  "cases": rows, "macro_recall_at_10": mean("recall_at_k"),
                  "macro_precision_at_10": mean("precision_at_k"),
                  "p50_ms": percentile([r["latency_ms"] for r in rows], .5),
                  "p95_ms": percentile([r["latency_ms"] for r in rows], .95),
                  "dense_recall": None, "human_acceptance": None}
        output = Path(options["out"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False))
