# -*- coding: utf-8 -*-
"""API People Intelligence — quyền + soi fact/review/alias (Master Plan §5, §21.2)."""
from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from accounts import roles
from people import resolution
from people.models import IdentityConflict, Person

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

    def test_review_bulk_resolve_accepts_selected_only(self):
        second = Person.objects.create(display_name="Ứng viên B")
        record_fact(second, "city", "Hà Nội", source_kind=ExtractedFact.SOURCE_AI,
                    confidence=0.4)  # low_confidence -> ReviewItem
        items = list(ReviewItem.objects.filter(status=ReviewItem.STATUS_OPEN)
                     .values_list("pk", flat=True))
        self.assertGreaterEqual(len(items), 2)
        self.client.force_authenticate(self.admin)

        resp = self.client.post("/api/v1/intel/review/bulk/",
                                {"ids": items, "decision": "accept"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json()["resolved"]), set(items))
        self.assertEqual(
            ReviewItem.objects.filter(pk__in=items, status=ReviewItem.STATUS_ACCEPTED).count(),
            len(items))

    def test_alias_bulk_resolve_accept_needs_entry_code(self):
        record_fact(self.person, "current_title", "Chuyên viên siêu lạ 1",
                    source_kind=ExtractedFact.SOURCE_EDGE, confidence=0.95)
        record_fact(self.person, "current_title", "Chuyên viên siêu lạ 2",
                    source_kind=ExtractedFact.SOURCE_EDGE, confidence=0.95)
        ids = list(CanonicalAlias.objects.filter(
            namespace__key="job_title", status=CanonicalAlias.STATUS_PROPOSED)
            .values_list("pk", flat=True))
        self.assertGreaterEqual(len(ids), 2)
        entry = CanonicalEntry.objects.get(namespace__key="job_title", code="business-analyst")
        self.client.force_authenticate(self.admin)

        missing_code = self.client.post("/api/v1/intel/aliases/bulk/",
                                        {"ids": ids, "decision": "accept"}, format="json")
        self.assertEqual(missing_code.status_code, 400)

        ok = self.client.post("/api/v1/intel/aliases/bulk/",
                              {"ids": ids, "decision": "accept", "entry_code": entry.code},
                              format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(set(ok.json()["resolved"]), set(ids))
        self.assertEqual(
            CanonicalAlias.objects.filter(pk__in=ids, status=CanonicalAlias.STATUS_ACCEPTED,
                                          entry=entry).count(),
            len(ids))

    def test_alias_new_entry_creates_and_links_but_never_overwrites_existing_code(self):
        record_fact(self.person, "current_title", "Chuyên viên vị trí hoàn toàn mới",
                    source_kind=ExtractedFact.SOURCE_EDGE, confidence=0.95)
        alias = CanonicalAlias.objects.get(
            namespace__key="job_title", alias_raw="Chuyên viên vị trí hoàn toàn mới")
        self.client.force_authenticate(self.admin)

        existing = CanonicalEntry.objects.get(namespace__key="job_title", code="business-analyst")
        original_label = existing.label
        collide = self.client.post(f"/api/v1/intel/aliases/{alias.pk}/new-entry/",
                                   {"code": existing.code, "label": "Nhãn khác hẳn"},
                                   format="json")
        self.assertEqual(collide.status_code, 400)
        existing.refresh_from_db()
        self.assertEqual(existing.label, original_label, "không được âm thầm ghi đè entry cũ")

        ok = self.client.post(f"/api/v1/intel/aliases/{alias.pk}/new-entry/",
                              {"code": "vi-tri-moi-hoan-toan", "label": "Vị trí mới hoàn toàn"},
                              format="json")
        self.assertEqual(ok.status_code, 200)
        alias.refresh_from_db()
        self.assertEqual(alias.status, CanonicalAlias.STATUS_ACCEPTED)
        self.assertEqual(alias.entry.code, "vi-tri-moi-hoan-toan")

    def test_identity_conflict_queue_and_resolve_admin_only(self):
        a = resolution.resolve({"source": "topcv", "account": "ta@msb.com.vn", "cv_id": "c1",
                                "fullname": "Chị A", "email": "cha@example.com",
                                "phone": "0911111111", "position": "", "city": ""}).person
        b = resolution.resolve({"source": "topcv", "account": "ta@msb.com.vn", "cv_id": "c2",
                                "fullname": "Anh B", "email": "anhb@example.com",
                                "phone": "0922222222", "position": "", "city": ""}).person
        resolution.resolve({"source": "topcv", "account": "ta@msb.com.vn", "cv_id": "c3",
                            "fullname": "?", "email": "cha@example.com",
                            "phone": "0922222222", "position": "", "city": ""})
        conflict = IdentityConflict.objects.get()

        self.client.force_authenticate(self.recruiter)
        self.assertEqual(self.client.get("/api/v1/intel/identity-conflicts/").status_code, 403)

        self.client.force_authenticate(self.admin)
        body = self.client.get("/api/v1/intel/identity-conflicts/").json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual({p["id"] for p in body["results"][0]["people"]}, {a.pk, b.pk})

        resp = self.client.post(
            f"/api/v1/intel/identity-conflicts/{conflict.pk}/resolve/",
            {"decision": "dismiss"}, format="json")
        self.assertEqual(resp.status_code, 200)
        conflict.refresh_from_db()
        self.assertEqual(conflict.status, IdentityConflict.STATUS_DISMISSED)

    def test_runs_dashboard_reports_conflict_count_and_alerts(self):
        resolution.resolve({"source": "topcv", "account": "ta@msb.com.vn", "cv_id": "d1",
                            "fullname": "Chị X", "email": "chix@example.com",
                            "phone": "0933333333", "position": "", "city": ""})
        resolution.resolve({"source": "topcv", "account": "ta@msb.com.vn", "cv_id": "d2",
                            "fullname": "Anh Y", "email": "anhy@example.com",
                            "phone": "0944444444", "position": "", "city": ""})
        resolution.resolve({"source": "topcv", "account": "ta@msb.com.vn", "cv_id": "d3",
                            "fullname": "?", "email": "chix@example.com",
                            "phone": "0944444444", "position": "", "city": ""})
        self.client.force_authenticate(self.admin)
        body = self.client.get("/api/v1/intel/runs/").json()
        self.assertEqual(body["totals"]["open_identity_conflicts"], 1)
        self.assertIn("alerts", body)
        self.assertFalse(body["alerts"]["conflicts"], "1 xung đột chưa vượt ngưỡng cảnh báo")
