# -*- coding: utf-8 -*-
"""`structured_match.match_requirements` + kỹ năng `match_candidate_job`.

Ghim ba điều: mỗi yêu cầu chỉ có ba trạng thái tất định (không có "gần đúng"),
"unknown" (câu không quy về được trường có cấu trúc) không bị lẫn với "missing"
(thật sự không khớp), và kỹ năng không dùng để so NHIỀU ứng viên với nhau.
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase

from accounts import roles
from ai import toolset
from intel.models import ExtractedFact
from people.models import Person
from talent.answer import structured_match
from talent.models import TalentProfile


def _fact(person, field, value, fp):
    return ExtractedFact.objects.create(
        person=person, field=field, raw_value=value, normalized_value=value,
        source_kind=ExtractedFact.SOURCE_AI, fingerprint=fp,
        status=ExtractedFact.STATUS_ACCEPTED, is_current=True)


class MatchRequirementsTest(TestCase):
    def test_ba_trang_thai_tren_mot_ung_vien(self):
        person = Person.objects.create(display_name="Ứng viên JD")
        _fact(person, "skills", "Python", "fp-skill")
        TalentProfile.objects.create(person=person, years_experience=1)

        rows = structured_match.match_requirements(person.pk, [
            "biết Python",                  # có trong ExtractedFact → satisfied
            "trên 3 năm kinh nghiệm",       # có trường, không đạt ngưỡng → missing
            "có tinh thần trách nhiệm cao", # không quy về trường nào → unknown
        ])
        by_req = {r["requirement"]: r["status"] for r in rows}
        self.assertEqual(by_req["biết Python"], "satisfied")
        self.assertEqual(by_req["trên 3 năm kinh nghiệm"], "missing")
        self.assertEqual(by_req["có tinh thần trách nhiệm cao"], "unknown")

    def test_chi_xet_dung_nguoi_duoc_hoi(self):
        """`universe_ids=[person_id]` — không được vô tình khớp nhờ người khác
        trong kho có cùng kỹ năng."""
        target = Person.objects.create(display_name="Người được hỏi")
        other = Person.objects.create(display_name="Người khác có Python")
        _fact(other, "skills", "Python", "fp-other")

        rows = structured_match.match_requirements(target.pk, ["biết Python"])
        self.assertEqual(rows[0]["status"], "missing")

    def test_cat_o_muc_toi_da(self):
        person = Person.objects.create(display_name="Nhiều yêu cầu")
        many = [f"yêu cầu tự do {i}" for i in range(structured_match.MAX_REQUIREMENTS + 5)]
        rows = structured_match.match_requirements(person.pk, many)
        self.assertEqual(len(rows), structured_match.MAX_REQUIREMENTS)


class MatchCandidateJobToolTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles.ensure_groups()

    def setUp(self):
        self.person = Person.objects.create(display_name="Ứng viên Tool")
        _fact(self.person, "skills", "Java", "fp-java")
        self.recruiter = User.objects.create_user("rec-jd", password="x")
        self.recruiter.groups.add(Group.objects.get(name=roles.RECRUITER))

    def test_visible_and_returns_counts_and_unknown_note(self):
        names = {t["function"]["name"] for t in toolset.agent_toolset_for("talent", self.recruiter)}
        self.assertIn("match_candidate_job", names)
        out = toolset.dispatch("match_candidate_job", {
            "person_id": self.person.pk, "role_title": "Java Developer",
            "requirements": ["biết Java", "biết Python", "chủ động trong công việc"]},
            user=self.recruiter, surface="talent")
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.result["satisfied_count"], 1)
        self.assertEqual(out.result["missing"], ["biết Python"])
        self.assertIn("chưa xác định được", out.result["note"])

    def test_requires_requirements(self):
        out = toolset.dispatch("match_candidate_job",
                               {"person_id": self.person.pk, "requirements": []},
                               user=self.recruiter, surface="talent")
        self.assertFalse(out.ok)

    def test_selection_guard_applies(self):
        out = toolset.dispatch("match_candidate_job",
                               {"person_id": self.person.pk, "requirements": ["biết Java"]},
                               user=self.recruiter, surface="talent",
                               context={"selected_person_ids": [self.person.pk + 1]})
        self.assertFalse(out.ok)
        self.assertIn("vừa chọn", out.error)

    def test_denied_without_talent_module(self):
        plain = User.objects.create_user("plain-jd", password="x")
        out = toolset.dispatch("match_candidate_job",
                               {"person_id": self.person.pk, "requirements": ["biết Java"]},
                               user=plain, surface="talent")
        self.assertFalse(out.ok)
