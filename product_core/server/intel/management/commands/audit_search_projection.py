"""Read-only readiness check for the materialized fact projection."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from intel.projection import audit


class Command(BaseCommand):
    help = "Audit MaterializedProfile version, fact identity and source provenance."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="")
        parser.add_argument("--gate", action="store_true")

    def handle(self, *args, **options):
        report = audit()
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if options["out"]:
            out = Path(options["out"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(rendered + "\n", encoding="utf-8")
        self.stdout.write(rendered)
        if options["gate"] and not report["ready"]:
            raise CommandError("Projection is not ready; do not migrate readers.")
