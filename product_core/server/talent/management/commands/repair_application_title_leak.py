from django.core.management.base import BaseCommand
from django.db import transaction

from people.models import Person
from talent.derive import apply_extracted_facts, derive
from talent.models import TalentProfile
from talent.search_v2 import build_dossier
from talent.vector_index import index_person


class Command(BaseCommand):
    help = ("Remove application-position values from Person.headline and rebuild "
            "the affected profile/search materializations.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--rebuild-all", action="store_true")

    def handle(self, *args, **options):
        affected = []
        people = Person.applicants().exclude(headline="").prefetch_related("source_records")
        for person in people.iterator(chunk_size=200):
            headline = person.headline.strip().casefold()
            positions = {
                str((record.payload or {}).get("position") or record.position or "")
                .strip().casefold()
                for record in person.source_records.all()
            }
            current_title = str(TalentProfile.objects.filter(person=person)
                                .values_list("current_title", flat=True).first()
                                or "").strip().casefold()
            posting_current_title = (current_title in positions
                                     and ("msb" in current_title or " - " in current_title))
            if (headline and headline in positions) or posting_current_title:
                affected.append(person.pk)

        self.stdout.write(f"application_title_headlines={len(affected)}")
        if not options["apply"]:
            self.stdout.write("dry-run; pass --apply to repair")
            return

        repaired = 0
        rebuild_ids = (list(Person.applicants().values_list("pk", flat=True))
                       if options["rebuild_all"] else affected)
        for person_id in rebuild_ids:
            with transaction.atomic():
                person = Person.objects.select_for_update().get(pk=person_id)
                if person_id in affected:
                    person.headline = ""
                    person.save(update_fields=["headline", "updated_at"])
                derive(person)
                apply_extracted_facts(person)
                build_dossier(person_id)
                # Rebuild text immediately. The background worker will replace
                # the now-stale profile embedding without blocking this repair.
                index_person(person_id, with_embeddings=False)
                repaired += int(person_id in affected)
        self.stdout.write(self.style.SUCCESS(
            f"repaired={repaired} rebuilt={len(rebuild_ids)}"))
