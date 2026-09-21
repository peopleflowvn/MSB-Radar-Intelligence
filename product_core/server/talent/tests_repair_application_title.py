from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.models import Edge, SourceRecord
from people.models import Person
from talent.models import SearchProjection, TalentProfile


class RepairApplicationTitleLeakTest(TestCase):
    def test_repairs_only_headline_equal_to_application_position(self):
        edge = Edge.objects.create(label="test")
        leaked = Person.objects.create(display_name="Leaked", headline="Finance Analyst")
        genuine = Person.objects.create(display_name="Genuine", headline="Data Analyst")
        TalentProfile.objects.create(person=leaked)
        TalentProfile.objects.create(person=genuine, current_title="Data Analyst")
        for index, person in enumerate((leaked, genuine), start=1):
            SourceRecord.objects.create(
                edge=edge, entity_type="candidate", entity_key=str(index), person=person,
                content_hash=str(index), status="resolved", position="Finance Analyst",
                payload={"position": "Finance Analyst"},
            )

        output = StringIO()
        call_command("repair_application_title_leak", "--apply", stdout=output)

        leaked.refresh_from_db()
        genuine.refresh_from_db()
        self.assertEqual(leaked.headline, "")
        self.assertEqual(genuine.headline, "Data Analyst")
        self.assertNotIn("finance analyst", SearchProjection.objects.get(
            person=leaked).searchable_text.casefold())
        self.assertIn("repaired=1", output.getvalue())
