# -*- coding: utf-8 -*-
"""ExtractedFact — idempotency, curated protection, bitemporal (Master Plan §5, §2.3, §21.1)."""
from django.test import TestCase
from django.utils import timezone

from people.models import Person
from talent.models import TalentProfile

from . import seeds
from .facts import current_facts, record_fact
from .models import ExtractedFact, ReviewItem


class RecordFactTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seeds.seed_all()

    def setUp(self):
        self.person = Person.objects.create(display_name="Ứng viên A")

    def test_idempotent_by_fingerprint(self):
        for _ in range(3):
            record_fact(self.person, "city", "Hà Nội",
                        source_kind=ExtractedFact.SOURCE_EDGE, confidence=0.95)
        self.assertEqual(
            ExtractedFact.objects.filter(person=self.person, field="city").count(), 1)
        fact = ExtractedFact.objects.get(person=self.person, field="city")
        self.assertEqual(fact.canonical_code, "VN-HN")
        self.assertEqual(fact.status, ExtractedFact.STATUS_ACCEPTED)

    def test_edge_value_accepted_even_with_unknown_alias(self):
        fact, _ = record_fact(self.person, "current_title", "Chức danh lạ hoắc",
                              source_kind=ExtractedFact.SOURCE_EDGE, confidence=0.95)
        self.assertEqual(fact.status, ExtractedFact.STATUS_ACCEPTED)
        self.assertEqual(fact.canonical_code, "")
        # alias vẫn vào hàng chờ
        from .models import CanonicalAlias
        self.assertTrue(CanonicalAlias.objects.filter(
            namespace__key="job_title", status=CanonicalAlias.STATUS_PROPOSED).exists())

    def test_curated_field_blocks_ai_overwrite(self):
        talent = TalentProfile.objects.create(person=self.person)
        record_fact(self.person, "current_company", "Ngân hàng MSB",
                    source_kind=ExtractedFact.SOURCE_MANUAL, confidence=1.0)
        talent.curated_fields = ["current_company"]
        talent.save()

        fact, _ = record_fact(self.person, "current_company", "Công ty AI đoán",
                              source_kind=ExtractedFact.SOURCE_AI, confidence=0.99,
                              extractor="radar_ai")
        self.assertEqual(fact.status, ExtractedFact.STATUS_CONFLICT)
        self.assertTrue(fact.review_items.filter(reason=ReviewItem.REASON_CONFLICT).exists())
        # giá trị người dùng vẫn là hiện hành
        current = current_facts(self.person, "current_company").first()
        self.assertEqual(current.source_kind, ExtractedFact.SOURCE_MANUAL)

    def test_bitemporal_latest_wins_for_current_title(self):
        old = timezone.now() - timezone.timedelta(days=400)
        new = timezone.now() - timezone.timedelta(days=10)
        record_fact(self.person, "current_title", "Data Analyst",
                    source_kind=ExtractedFact.SOURCE_EDGE, observed_at=old, confidence=0.95)
        record_fact(self.person, "current_title", "Business Analyst",
                    source_kind=ExtractedFact.SOURCE_EDGE, observed_at=new, confidence=0.95)
        current = list(current_facts(self.person, "current_title"))
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].canonical_code, "business-analyst")
        stale = ExtractedFact.objects.get(person=self.person, field="current_title",
                                          canonical_code="data-analyst")
        self.assertFalse(stale.is_current)
        self.assertEqual(stale.valid_to, current[0].observed_at)

    def test_merge_field_keeps_all_current(self):
        for skill in ("SQL", "Python", "Power BI"):
            record_fact(self.person, "skills", skill,
                        source_kind=ExtractedFact.SOURCE_EDGE, confidence=0.9)
        codes = {f.canonical_code for f in current_facts(self.person, "skills")}
        self.assertEqual(codes, {"sql", "python", "power-bi"})

    def test_sensitive_ai_fact_goes_to_review(self):
        fact, _ = record_fact(self.person, "expected_salary", "30 triệu",
                              source_kind=ExtractedFact.SOURCE_AI, confidence=0.99,
                              extractor="radar_ai")
        self.assertEqual(fact.status, ExtractedFact.STATUS_PROPOSED)
        self.assertTrue(fact.review_items.filter(reason=ReviewItem.REASON_SENSITIVE).exists())

    def test_low_confidence_ai_fact_needs_review(self):
        fact, _ = record_fact(self.person, "major", "Khoa học máy tính",
                              source_kind=ExtractedFact.SOURCE_AI, confidence=0.4,
                              extractor="radar_ai")
        self.assertEqual(fact.status, ExtractedFact.STATUS_PROPOSED)
        self.assertTrue(fact.review_items.filter(
            reason=ReviewItem.REASON_LOW_CONFIDENCE).exists())

    def test_high_confidence_ai_fact_auto_accepts(self):
        fact, _ = record_fact(self.person, "skills", "Kubernetes",
                              source_kind=ExtractedFact.SOURCE_AI, confidence=0.95,
                              extractor="radar_ai")
        self.assertEqual(fact.status, ExtractedFact.STATUS_ACCEPTED)
