"""Score a completed two-reviewer worksheet without calling an LLM."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ai.review_eval import score_batch


class Command(BaseCommand):
    help = "Score independent human review labels; null for missing/disputed truth."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--out", required=True)
        parser.add_argument("--require-complete", action="store_true")

    def handle(self, *args, **options):
        try:
            manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8"))
            records = [json.loads(line) for line in
                       Path(options["file"]).read_text(encoding="utf-8").splitlines()
                       if line.strip()]
        except (OSError, ValueError) as exc:
            raise CommandError(f"Cannot read review batch: {exc}")
        report = score_batch(manifest, records)
        out = Path(options["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(json.dumps(report, ensure_ascii=False))
        if options["require_complete"] and not report["complete"]:
            raise CommandError("Human review is incomplete or disputed; acceptance is NOT MEASURED.")
