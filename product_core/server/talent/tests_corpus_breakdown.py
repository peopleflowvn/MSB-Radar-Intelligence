# -*- coding: utf-8 -*-
"""Thống kê toàn kho CÓ LỌC — `corpus.breakdown` + kỹ năng `aggregate_corpus`.

Ghim ba điều: lọc khớp nguyên cụm đã bỏ dấu ("java" không ăn "javascript"),
hồ sơ để trống trường lọc không bị tính vào nhóm nhưng được báo độ phủ riêng,
và câu hỏi chỉ được gắn điều kiện lọc bằng giá trị CÓ THẬT trong kho.
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase

from accounts import roles
from ai import toolset
from people.models import Person
from talent.answer import corpus, engine, plan
from talent.models import TalentProfile


def _profile(name, **fields):
    person = Person.objects.create(display_name=name)
    return TalentProfile.objects.create(person=person, **fields)


class BreakdownTest(TestCase):
    def setUp(self):
        _profile("A", location="Hà Nội", skills=["Java", "SQL"], current_company="MSB")
        _profile("B", location="Ha Noi", skills=["Java"], current_company="MSB")
        _profile("C", location="Hồ Chí Minh", skills=["JavaScript", "SQL"])
        _profile("D", location="", skills=["Java"])
        reference = Person.objects.create(display_name="Tham chiếu", is_applicant=False)
        TalentProfile.objects.create(person=reference, location="Hà Nội", skills=["Java"])

    def test_filter_matches_folded_phrase_and_reports_filter_coverage(self):
        block = corpus.breakdown("skills", filters={"location": "hà nội"})
        self.assertEqual(block["total"], 2)
        self.assertEqual(block["store_total"], 4)
        self.assertEqual(block["top"][0], {"value": "Java", "count": 2})
        self.assertEqual(block["filters"][0]["filled"], 3)

    def test_skill_filter_is_whole_phrase(self):
        block = corpus.breakdown("location", filters={"skills": "java"})
        self.assertEqual(block["total"], 3)            # A, B, D — không có C (JavaScript)
        self.assertEqual(block["filled"], 2)

    def test_unfiltered_counts_applicants_only(self):
        block = corpus.breakdown("skills")
        self.assertEqual(block["total"], 4)
        self.assertEqual(block["top"][0], {"value": "Java", "count": 3})

    def test_rejects_unknown_fields(self):
        with self.assertRaises(ValueError):
            corpus.breakdown("person__email")
        with self.assertRaises(ValueError):
            corpus.breakdown("skills", filters={"expected_salary": "10"})

    def test_question_uses_only_values_present_in_store(self):
        block = corpus.breakdown_for_question("kỹ năng phổ biến nhất của ứng viên ở Hà Nội")
        self.assertEqual(block["field"], "skills")
        self.assertEqual(block["filters"][0]["field"], "location")
        self.assertIsNone(corpus.breakdown_for_question("kỹ năng phổ biến nhất ở Đà Nẵng"))
        self.assertIsNone(corpus.breakdown_for_question("kỹ năng nào phổ biến nhất trong kho"))

    def test_analyze_prompt_gets_filtered_block(self):
        facts = engine._corpus_facts(plan.QueryPlan(
            shape="analyze", information_need="kỹ năng phổ biến của người ở Hà Nội"))
        self.assertIn("THỐNG KÊ CÓ LỌC", facts)
        self.assertIn("Java (2)", facts)
        plain = engine._corpus_facts(plan.QueryPlan(
            shape="analyze", information_need="tổng quan kho ứng viên"))
        self.assertNotIn("THỐNG KÊ CÓ LỌC", plain)


class AggregateCorpusToolTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles.ensure_groups()

    def setUp(self):
        _profile("A", location="Hà Nội", skills=["Java"])
        self.recruiter = User.objects.create_user("rec-agg", password="x")
        self.recruiter.groups.add(Group.objects.get(name=roles.RECRUITER))

    def test_visible_to_talent_and_returns_counts_not_people(self):
        names = {t["function"]["name"] for t in toolset.agent_toolset_for("talent", self.recruiter)}
        self.assertIn("aggregate_corpus", names)
        out = toolset.dispatch("aggregate_corpus",
                               {"field": "skills", "filters": {"location": "Hà Nội"}},
                               user=self.recruiter, surface="talent")
        self.assertTrue(out.ok, out.error)
        self.assertEqual(out.result["top"], [{"value": "Java", "count": 1}])
        self.assertNotIn("A", str(out.result["top"]))
        self.assertEqual(toolset.label_of("aggregate_corpus"), "Thống kê toàn kho")

    def test_denied_without_talent_module_and_bad_field_is_tool_error(self):
        plain = User.objects.create_user("plain-agg", password="x")
        self.assertFalse(toolset.dispatch("aggregate_corpus", {"field": "skills"},
                                          user=plain, surface="talent").ok)
        out = toolset.dispatch("aggregate_corpus", {"field": "password"},
                               user=self.recruiter, surface="talent")
        self.assertFalse(out.ok)
        self.assertIn("không thống kê được", out.error)
