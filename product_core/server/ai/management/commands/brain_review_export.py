"""Create a versioned, two-reviewer worksheet from a Brain/Answer eval report."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ai.review_eval import build_batch


class Command(BaseCommand):
    help = "Export blank independent-human-review records from an evaluation JSON."

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True)
        parser.add_argument("--out", required=True, help="Output directory (keep production data ignored).")

    def handle(self, *args, **options):
        try:
            report = json.loads(Path(options["input"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError(f"Cannot read input report: {exc}")
        manifest, records = build_batch(report)
        out = Path(options["out"])
        if (out / "manifest.json").exists() or (out / "reviews.jsonl").exists():
            raise CommandError("Output batch already exists; choose a new directory to preserve labels.")
        out.mkdir(parents=True, exist_ok=True)
        (out / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with (out / "reviews.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.stdout.write(self.style.SUCCESS(
            f"Exported {len(records)} review records; metrics remain NOT MEASURED until labelled."))
