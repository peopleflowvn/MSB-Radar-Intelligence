# -*- coding: utf-8 -*-
"""API People Intelligence — quyền + soi fact/review/alias (Master Plan §5, §21.2)."""
from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from accounts import roles
from people.models import Person

from . import seeds
from .facts import record_fact
from .models import CanonicalAlias, CanonicalEntry, ExtractedFact, ReviewItem


def _user(name, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(name, password="x")
    for role in role_names:
        user.groups.add(Group.objects.get(name=role))
    return user


class IntelApiTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        seeds.seed_all()

    def setUp(self):
        self.recruiter = _user("rec", roles.RECRUITER)
        self.admin = _user("adm", roles.ADMIN)
        self.person = Person.objects.create(display_name="Ứng viên A")
        record_fact(self.person, "city", "TP.HCM",
                    source_kind=ExtractedFact.SOURCE_EDGE, confidence=0.95,
                    evidence="Địa chỉ: Quận 1")
        record_fact(self.person, "expected_salary", "40tr",
                    source_kind=ExtractedFact.SOURCE_AI, confidence=0.9, extractor="radar_ai")

    def test_person_facts_requires_talent_and_returns_provenance(self):
        self.assertIn(self.client.get(
            f"/api/v1/intel/people/{self.person.pk}/facts/").status_code, (401, 403))

        self.client.force_authenticate(self.recruiter)
        body = self.client.get(f"/api/v1/intel/people/{self.person.pk}/facts/").json()
        self.assertIn("city", body["fields"])
        city = body["fields"]["city"][0]
        self.assertEqual(city["canonical_code"], "VN-SG")
        self.assertEqual(city["source_kind"], "edge")
        self.assertEqual(city["evidence"], "Địa chỉ: Quận 1")
        self.assertIn("city", body["current"])
        self.assertNotIn("expected_salary", body["current"])   # còn proposed

    def test_review_queue_admin_only(self):
        self.client.force_authenticate(self.recruiter)
        self.assertEqual(self.client.get("/api/v1/intel/review/").status_code, 403)

        self.client.force_authenticate(self.admin)
        body = self.client.get("/api/v1/intel/review/").json()
        self.assertTrue(any(it["reason"] == ReviewItem.REASON_SENSITIVE
                            for it in body["results"]))

    def test_review_resolve_accept_promotes_fact(self):
        item = ReviewItem.objects.get(reason=ReviewItem.REASON_SENSITIVE)
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f"/api/v1/intel/review/{item.pk}/",
                                {"decision": "accept"}, format="json")
        self.assertEqual(resp.status_code, 200)
        item.fact.refresh_from_db()
        self.assertEqual(item.fact.status, ExtractedFact.STATUS_ACCEPTED)

    def test_alias_queue_and_accept_needs_valid_entry(self):
        record_fact(self.person, "current_title", "Chuyên viên siêu lạ",
                    source_kind=ExtractedFact.SOURCE_EDGE, confidence=0.95)
        alias = CanonicalAlias.objects.get(
            namespace__key="job_title", status=CanonicalAlias.STATUS_PROPOSED)
        self.client.force_authenticate(self.admin)

        bad = self.client.post(f"/api/v1/intel/aliases/{alias.pk}/",
                               {"decision": "accept", "entry_code": "khong-ton-tai"},
                               format="json")
        self.assertEqual(bad.status_code, 400)

        entry = CanonicalEntry.objects.get(namespace__key="job_title", code="business-analyst")
        ok = self.client.post(f"/api/v1/intel/aliases/{alias.pk}/",
                              {"decision": "accept", "entry_code": entry.code}, format="json")
        self.assertEqual(ok.status_code, 200)
        alias.refresh_from_db()
        self.assertEqual(alias.status, CanonicalAlias.STATUS_ACCEPTED)
        self.assertEqual(alias.entry, entry)
        self.assertEqual(alias.approved_by, "adm")

    def test_runs_dashboard_admin_only(self):
        self.client.force_authenticate(self.recruiter)
        self.assertEqual(self.client.get("/api/v1/intel/runs/").status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get("/api/v1/intel/runs/").status_code, 200)

    def test_contact_mention_queue_and_accept(self):
        """Người tham chiếu bóc từ CV giờ có API — trước chỉ xem được ở Django admin."""
        from people.models import ContactMention, PersonLink
        ContactMention.objects.create(
            subject=self.person, full_name="Thuỳ PT", company="SeABank",
            email="thuy.pt@seabank.com.vn", phone="", email_raw="thuy.pt@seabank.com.vn",
            kind=ContactMention.KIND_REFERENCE, confidence=0.9,
            evidence="NGƯỜI THAM CHIẾU", extractor="radar_contacts",
            fingerprint="fp-api-1")

        self.client.force_authenticate(self.recruiter)
        self.assertEqual(self.client.get("/api/v1/intel/contacts/").status_code, 403)

        self.client.force_authenticate(self.admin)
        body = self.client.get("/api/v1/intel/contacts/").json()
        self.assertEqual(len(body["results"]), 1)
        mid = body["results"][0]["id"]

        resp = self.client.post(f"/api/v1/intel/contacts/{mid}/",
                                {"decision": "accept"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.json()["linked_person_id"])
        self.assertTrue(PersonLink.objects.filter(subject=self.person).exists())
