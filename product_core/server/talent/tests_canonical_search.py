# -*- coding: utf-8 -*-
"""Bộ lọc canonical trong search (Master Plan §8.1, §18 bước 8)."""
from django.test import TestCase

from intel import seeds
from intel.facts import record_fact
from intel.models import ExtractedFact
from people.models import Person
from talent import search as search_module
from talent.models import TalentProfile


class CanonicalSearchTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seeds.seed_all()

    def setUp(self):
        self.hn = Person.objects.create(display_name="Ứng viên HN")
        self.sg = Person.objects.create(display_name="Ứng viên SG")
        for p in (self.hn, self.sg):
            TalentProfile.objects.create(person=p)
        record_fact(self.hn, "city", "Hà Nội", source_kind=ExtractedFact.SOURCE_EDGE,
                    confidence=0.95)
        record_fact(self.sg, "city", "Sài Gòn", source_kind=ExtractedFact.SOURCE_EDGE,
                    confidence=0.95)
        record_fact(self.hn, "skills", "Power BI", source_kind=ExtractedFact.SOURCE_EDGE,
                    confidence=0.9)

    def test_canonical_code_filter_narrows_by_location(self):
        total, people = search_module.search(
            canonical_codes={"city": ["VN-HN"]}, ai_mode=True, limit=20)
        self.assertEqual({p.pk for p in people}, {self.hn.pk})

    def test_canonical_skill_filter_ignored_in_ai_mode_keeps_recall(self):
        # ai_mode chỉ áp canonical cho địa điểm; skill giữ recall cho scoring.
        _total, people = search_module.search(
            canonical_codes={"skills": ["power-bi"]}, ai_mode=True, limit=20)
        self.assertIn(self.sg.pk, {p.pk for p in people})   # không bị loại

    def test_skill_filter_applies_outside_ai_mode(self):
        _total, people = search_module.search(
            canonical_codes={"skills": ["power-bi"]}, ai_mode=False, limit=20)
        self.assertEqual({p.pk for p in people}, {self.hn.pk})

    def test_no_matching_facts_falls_back_to_no_filter(self):
        # Mã chưa ai có fact -> không lọc (không trả rỗng oan).
        total, people = search_module.search(
            canonical_codes={"city": ["VN-DN"]}, ai_mode=False, limit=20)
        self.assertEqual(total, Person.objects.count())

    # Test cờ INTEL_CANONICAL_SEARCH đã bỏ cùng `ai_search._canonical_codes`:
    # cờ đó chỉ chi phối bước nối tiêu chí → mã canonical của đường trả lời cũ.
    # Bộ lọc canonical trong `search.py` (bốn test trên) vẫn nguyên.
