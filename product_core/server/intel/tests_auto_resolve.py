# -*- coding: utf-8 -*-
"""Tự động nối alias 'proposed' — không bao giờ tạo canonical mới (§6, §21.2).

Bù cho lượng hàng chờ alias lớn (đòi hỏi tự động hoá thay vì duyệt tay từng
cái), nhưng vẫn giữ nguyên tắc "AI không tự tạo canonical code mới": mọi khớp
tự động đều nối vào một `CanonicalEntry` ĐÃ TỒN TẠI từ trước khi test chạy.
"""
from django.test import TestCase

from . import seeds
from .aliasing import auto_resolve
from .models import CanonicalAlias
from .registry import resolve


class AutoResolveAliasesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seeds.seed_all()

    def _propose(self, namespace, raw_value):
        res = resolve(namespace, raw_value)
        self.assertTrue(res.created_candidate, f"{raw_value!r} lẽ ra phải vào hàng chờ")
        return res.alias

    def test_dry_run_never_writes(self):
        alias = self._propose("skill", "powerbii")  # lỗi gõ nhầm của "power bi"
        report = auto_resolve(namespace_key="skill", apply=False)
        alias.refresh_from_db()
        self.assertEqual(alias.status, CanonicalAlias.STATUS_PROPOSED)
        self.assertFalse(report.apply)

    def test_close_typo_is_auto_linked_to_existing_entry(self):
        alias = self._propose("skill", "powerbii")
        report = auto_resolve(namespace_key="skill", apply=True)
        alias.refresh_from_db()
        self.assertEqual(alias.status, CanonicalAlias.STATUS_ACCEPTED)
        self.assertEqual(alias.entry.code, "power-bi")
        self.assertEqual(alias.source, "radar_ai")  # nguồn tạo giữ nguyên
        self.assertEqual(alias.approved_by, "ai_auto")
        self.assertIn("auto:", alias.note)
        decision = next(d for d in report.decisions if d.alias_id == alias.pk)
        self.assertEqual(decision.decision, "auto_accepted")

    def test_genuinely_new_value_is_left_for_a_human(self):
        alias = self._propose("skill", "Kỹ năng hoàn toàn chưa từng thấy trong hệ thống")
        report = auto_resolve(namespace_key="skill", apply=True)
        alias.refresh_from_db()
        self.assertEqual(alias.status, CanonicalAlias.STATUS_PROPOSED)
        self.assertIsNone(alias.entry_id)
        decision = next(d for d in report.decisions if d.alias_id == alias.pk)
        self.assertIn(decision.decision, ("needs_human", "no_candidates"))

    def test_never_creates_a_canonical_entry(self):
        from .models import CanonicalEntry
        before = CanonicalEntry.objects.count()
        self._propose("skill", "powerbii")
        self._propose("skill", "Kỹ năng hoàn toàn chưa từng thấy trong hệ thống")
        auto_resolve(apply=True)
        self.assertEqual(CanonicalEntry.objects.count(), before)

    def test_threshold_controls_how_aggressive_auto_linking_is(self):
        # Cùng một khớp (score ~0.93) — ngưỡng mặc định nối, ngưỡng khắt khe hơn thì không.
        alias = self._propose("skill", "powerbii")
        auto_resolve(namespace_key="skill", apply=True, threshold=0.97)
        alias.refresh_from_db()
        self.assertEqual(alias.status, CanonicalAlias.STATUS_PROPOSED)

    def test_namespace_filter_does_not_touch_other_namespaces(self):
        skill_alias = self._propose("skill", "powerbii")
        location_alias = self._propose("location", "Ha Nooi")
        auto_resolve(namespace_key="skill", apply=True)
        skill_alias.refresh_from_db()
        location_alias.refresh_from_db()
        self.assertEqual(skill_alias.status, CanonicalAlias.STATUS_ACCEPTED)
        self.assertEqual(location_alias.status, CanonicalAlias.STATUS_PROPOSED)

    def test_resolve_after_auto_accept_returns_the_linked_entry(self):
        self._propose("skill", "powerbii")
        auto_resolve(namespace_key="skill", apply=True)
        self.assertEqual(resolve("skill", "powerbii", propose=False).code, "power-bi")
