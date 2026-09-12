# -*- coding: utf-8 -*-
"""Canonical Registry — resolve, governance, no-auto-create (Master Plan §6, §21.2, §16.4)."""
from django.test import TestCase

from . import seeds
from .models import CanonicalAlias, CanonicalEntry
from .registry import add_alias, ensure_namespace, resolve, upsert_entry


class CanonicalResolveTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seeds.seed_all()

    def test_mandatory_test_cases_16_4(self):
        for value in ("TP HCM", "HCM", "Thành phố Hồ Chí Minh", "Sài Gòn", "Quận 1"):
            self.assertEqual(resolve("location", value).code, "VN-SG", value)
        for value in ("PowerBI", "Power BI", "Microsoft Power BI"):
            self.assertEqual(resolve("skill", value).code, "power-bi", value)
        for value in ("Bachelor", "Cử nhân", "Đại học"):
            self.assertEqual(resolve("education_level", value).code, "bachelor", value)

    def test_data_vs_data_analysis_are_parent_child_not_flat_alias(self):
        analysis = resolve("skill", "phân tích dữ liệu")
        field = resolve("skill", "data")
        self.assertEqual(analysis.code, "data-analysis")
        self.assertEqual(field.code, "data")
        self.assertEqual(
            CanonicalEntry.objects.get(namespace__key="skill", code="data-analysis")
            .parent.code, "data")

    def test_unknown_value_creates_candidate_never_an_entry(self):
        before = CanonicalEntry.objects.filter(namespace__key="skill").count()
        res = resolve("skill", "Kỹ năng chưa từng thấy")
        self.assertEqual(res.code, "")
        self.assertTrue(res.created_candidate)
        self.assertEqual(res.alias.status, CanonicalAlias.STATUS_PROPOSED)
        self.assertIsNone(res.alias.entry_id)
        self.assertEqual(CanonicalEntry.objects.filter(namespace__key="skill").count(), before)

    def test_resolve_propose_false_does_not_queue(self):
        res = resolve("skill", "Không đề xuất nhé", propose=False)
        self.assertIsNone(res.alias)
        self.assertFalse(CanonicalAlias.objects.filter(alias_norm="khong de xuat he").exists())

    def test_alias_accept_records_governance_and_lineage(self):
        ns = ensure_namespace("skill", "Kỹ năng")
        entry = upsert_entry(ns, "golang", "Go")
        res = resolve("skill", "gogo lang")
        alias = res.alias
        alias.accept(entry, by="admin@msb", note="đồng nghĩa Go")
        alias.refresh_from_db()
        self.assertEqual(alias.status, CanonicalAlias.STATUS_ACCEPTED)
        self.assertEqual(alias.entry, entry)
        self.assertEqual(alias.approved_by, "admin@msb")
        self.assertEqual(alias.version, 2)
        self.assertIsNotNone(alias.effective_at)
        self.assertEqual(alias.previous["status"], CanonicalAlias.STATUS_PROPOSED)
        # sau accept thì resolve trả code
        self.assertEqual(resolve("skill", "GoGo Lang").code, "golang")

    def test_seed_is_idempotent(self):
        n1 = CanonicalEntry.objects.count()
        seeds.seed_all()
        self.assertEqual(CanonicalEntry.objects.count(), n1)


class AddAliasTest(TestCase):
    def test_add_alias_attaches_accepted(self):
        ns = ensure_namespace("language", "Ngôn ngữ")
        entry = upsert_entry(ns, "ja", "Tiếng Nhật")
        add_alias(ns, "tieng nhat", entry, source="seed")
        add_alias(ns, "japanese", entry, source="seed")
        self.assertEqual(resolve("language", "Japanese").code, "ja")
        self.assertEqual(resolve("language", "tiếng Nhật").code, "ja")
