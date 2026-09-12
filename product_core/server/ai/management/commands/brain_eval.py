"""Run Brain V2 contracts without touching the corpus or calling providers."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ai.brain_eval import contract_report


class Command(BaseCommand):
    help = "Deterministic Brain V2 contracts; nonzero exit on failed contracts."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True)

    def handle(self, *args, **options):
        report = contract_report()
        output = Path(options["out"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(f"{report['passed']}/{report['total']} contracts passed; {output}")
        if report["passed"] != report["total"]:
            raise CommandError("Architecture contract failures; see report. Not a live quality score.")
