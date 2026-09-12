from django.core.management.base import BaseCommand
from people.models import Person

from talent.semantic_index import index_person


class Command(BaseCommand):
    help = "Rebuild the provider-independent semantic index for all active people."

    def handle(self, *args, **options):
        total = Person.objects.filter(merged_into__isnull=True).count()
        for position, person_id in enumerate(
                Person.objects.filter(merged_into__isnull=True).values_list("pk", flat=True).iterator(), 1):
            index_person(person_id)
            if position % 250 == 0:
                self.stdout.write(f"{position}/{total}")
        self.stdout.write(self.style.SUCCESS(f"Indexed {total} people"))
