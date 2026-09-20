from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from people.models import Person
from talent.models import SearchProjection


class SearchScaleFixtureTest(TestCase):
    def test_generate_requires_explicit_confirmation(self):
        with self.assertRaises(CommandError):
            call_command("search_scale_fixture", "generate", count=10)

    def test_small_fixture_is_reproducible_and_benchmarkable(self):
        out = StringIO()
        call_command("search_scale_fixture", "generate", count=20, seed=7,
                     batch_size=7, confirm=True, stdout=out)
        self.assertEqual(Person.objects.filter(display_name__startswith="SYNTH-7-").count(), 20)
        self.assertEqual(SearchProjection.objects.count(), 20)
        bench = StringIO()
        call_command("search_scale_fixture", "benchmark", stdout=bench)
        self.assertIn("count_ms", bench.getvalue())
