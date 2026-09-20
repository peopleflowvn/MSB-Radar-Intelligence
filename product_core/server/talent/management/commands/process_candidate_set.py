from django.core.management.base import BaseCommand

from talent.search_v2 import process_candidate_set


class Command(BaseCommand):
    help = "Resume deterministic T2 processing for a durable CandidateSet run."

    def add_arguments(self, parser):
        parser.add_argument("run_id")
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        run = process_candidate_set(options["run_id"], batch_size=options["batch_size"])
        self.stdout.write(
            f"run={run.pk} state={run.state} judged={run.judged} "
            f"unknown={run.unknown} not_read={run.not_read} cursor={run.cursor}")
