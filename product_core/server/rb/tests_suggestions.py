# -*- coding: utf-8 -*-
"""RB Growth Engine — chấm điểm 5 chiều và vòng đời đề xuất (Master Plan mục 33–35).

Ba điều bài này canh kỹ nhất:

1. **Máy đề xuất, người quyết định.** Không có đường nào để hệ thống tự nhận
   cơ hội thay RM — `test_nhan_KHONG_THE_thieu_nguoi_nhan` canh đúng chỗ đó.
2. **Điểm luôn kèm lý do.** Một con số không giải thích được là thứ RM sẽ ngừng
   tin sau vài lần gọi trượt, và lúc đó mất cả sản phẩm chứ không riêng con số.
3. **Chưa có số điện thoại KHÁC với khách từ chối.** Gộp hai thứ này là bỏ mất
   đúng nhóm khách đáng giá nhất của Social Radar.
"""
from datetime import timedelta

from accounts import roles
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from people.models import Person, Relationship, Signal

from . import scoring, suggestions
from .models import (PRODUCT_FX, PRODUCT_MORTGAGE, OpportunityOutcome,
                     OpportunitySuggestion, ProductValueConfig, RBOpportunity,
                     RBProfile)


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class ScoringTest(TestCase):
    """Chấm điểm 5 chiều — tất định, giải thích được, không có LLM."""

    def setUp(self):
        self.an = Person.objects.create(display_name="Nguyen Van An",
                                        primary_phone="+84901234567",
                                        primary_email="an@example.com")

    def test_moi_chieu_LUON_kem_ly_do(self):
        fit, fit_why = scoring.score_fit(self.an, PRODUCT_MORTGAGE)
        timing, timing_why = scoring.score_timing(timezone.now())
        reach, reach_why = scoring.score_reachability(self.an)
        value, value_why, _weight = scoring.score_value(PRODUCT_MORTGAGE)
        for score, why in ((fit, fit_why), (timing, timing_why),
                           (reach, reach_why), (value, value_why)):
            self.assertTrue(why, "Diem khong kem ly do la diem khong dung duoc")
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_diem_uu_tien_dung_cong_thuc_da_cong_bo(self):
        """Cong thuc phai khop Master Plan muc 15, khong duoc lech am tham."""
        got = scoring.priority_score(80, 60, 100, 40, 50)
        mong_doi = 80 * 0.25 + 60 * 0.25 + 100 * 0.25 + 40 * 0.15 + 50 * 0.10
        self.assertAlmostEqual(got, round(mong_doi, 2))

    def test_tong_trong_so_bang_mot(self):
        self.assertAlmostEqual(sum(scoring.WEIGHTS.values()), 1.0)

    def test_he_so_chien_luoc_NHAN_chu_khong_cong(self):
        binh_thuong = scoring.priority_score(60, 60, 60, 60, 60)
        day_manh = scoring.priority_score(60, 60, 60, 60, 60, strategic_weight=1.5)
        self.assertAlmostEqual(day_manh, round(binh_thuong * 1.5, 2))

    def test_diem_khong_bao_gio_vuot_ra_ngoai_0_100(self):
        self.assertLessEqual(
            scoring.priority_score(100, 100, 100, 100, 100, strategic_weight=5.0), 100)
        self.assertGreaterEqual(scoring.priority_score(0, 0, 0, 0, 0), 0)

    def test_timing_theo_bac_thang_da_cong_bo(self):
        now = timezone.now()
        self.assertEqual(scoring.score_timing(now - timedelta(days=3), now=now)[0], 100)
        self.assertEqual(scoring.score_timing(now - timedelta(days=20), now=now)[0], 70)
        self.assertEqual(scoring.score_timing(now - timedelta(days=60), now=now)[0], 40)
        self.assertLess(scoring.score_timing(now - timedelta(days=400), now=now)[0], 20)

    def test_khong_ro_thoi_diem_thi_khong_cho_diem_cao(self):
        score, why = scoring.score_timing(None)
        self.assertLessEqual(score, 40)
        self.assertTrue(why)

    def test_DNC_cho_thang_khong_diem(self):
        relation = Relationship.objects.create(
            person=self.an, domain=Signal.DOMAIN_RB, state="cold",
            do_not_contact=True)
        score, why = scoring.score_reachability(self.an, relationship=relation)
        self.assertEqual(score, 0.0)
        self.assertIn("DNC", " ".join(why))

    def test_chua_co_lien_he_KHAC_voi_DNC(self):
        """Chua co so la tro ngai; DNC la dieu kien chan. Khong duoc gop."""
        khong_lien_he = Person.objects.create(display_name="Chua co so")
        score, why = scoring.score_reachability(khong_lien_he)
        self.assertGreater(score, 0, "Chua co so khong duoc coi nhu khach tu choi")
        self.assertEqual(score, scoring.NO_CONTACT_SCORE)
        self.assertTrue(why)

    def test_vua_lien_he_thi_bi_tru_diem(self):
        """Goi lai sau ba ngay la lam phien, khong phai cham soc."""
        profile = RBProfile.objects.create(
            person=self.an, last_contact_at=timezone.now() - timedelta(days=3))
        gan = scoring.score_reachability(self.an, profile=profile)[0]
        profile.last_contact_at = timezone.now() - timedelta(days=60)
        xa = scoring.score_reachability(self.an, profile=profile)[0]
        self.assertLess(gan, xa)

    def test_gia_tri_doc_tu_cau_hinh_khong_hardcode(self):
        """Doi cau hinh phai doi diem — neu khong thi so nam trong code."""
        truoc = scoring.score_value(PRODUCT_MORTGAGE)[0]
        ProductValueConfig.objects.filter(product=PRODUCT_MORTGAGE).update(
            value_band=ProductValueConfig.BAND_LOW)
        sau = scoring.score_value(PRODUCT_MORTGAGE)[0]
        self.assertLess(sau, truoc)

    def test_so_that_thang_thang_dinh_tinh(self):
        ProductValueConfig.objects.filter(product=PRODUCT_MORTGAGE).update(
            value_band=ProductValueConfig.BAND_LOW, value_weight=95.0)
        score, why, _weight = scoring.score_value(PRODUCT_MORTGAGE)
        self.assertEqual(score, 95.0)
        self.assertIn("95", " ".join(why))

    def test_chua_cau_hinh_thi_trung_tinh_va_noi_ro(self):
        ProductValueConfig.objects.filter(product=PRODUCT_FX).delete()
        score, why, weight = scoring.score_value(PRODUCT_FX)
        self.assertEqual(score, 50.0)
        self.assertEqual(weight, 1.0)
        self.assertIn(u"Chưa cấu hình".lower(), " ".join(why).lower())

    def test_khong_lien_he_duoc_thi_viec_can_lam_la_di_xin_thong_tin(self):
        action = scoring.recommend_action({"reachability": 0, "need": 90,
                                           "timing": 100, "priority": 80})
        self.assertEqual(action, OpportunitySuggestion.ACTION_ASK_FOR_INFORMATION)

    def test_chua_co_kenh_lien_he_thi_di_xin_thong_tin_du_diem_cao(self):
        """Nhan tin cho nguoi khong co so dien thoai la hanh dong khong lam duoc."""
        action = scoring.recommend_action(
            {"reachability": scoring.NO_CONTACT_SCORE, "need": 85,
             "timing": 100, "priority": 70}, has_contact=False)
        self.assertEqual(action, OpportunitySuggestion.ACTION_ASK_FOR_INFORMATION)

    def test_nhu_cau_ro_con_nong_va_goi_duoc_thi_goi_ngay(self):
        action = scoring.recommend_action({"reachability": 80, "need": 85,
                                           "timing": 100, "priority": 85})
        self.assertEqual(action, OpportunitySuggestion.ACTION_CALL_NOW)

    def test_tin_hieu_nguoi_thi_cho_chu_khong_goi(self):
        action = scoring.recommend_action({"reachability": 80, "need": 60,
                                           "timing": 20, "priority": 50})
        self.assertEqual(action, OpportunitySuggestion.ACTION_WAIT)

    def test_da_co_co_hoi_dang_mo_thi_theo_doi_chu_khong_tao_viec_moi(self):
        action = scoring.recommend_action({"reachability": 80, "need": 85,
                                           "timing": 100, "priority": 85},
                                          has_open_opportunity=True)
        self.assertEqual(action, OpportunitySuggestion.ACTION_FOLLOW_UP)

    def test_ket_qua_cu_cho_phep_kich_hoat_lai(self):
        action = scoring.recommend_action(
            {"reachability": 80, "need": 85, "timing": 100, "priority": 85},
            previous_outcome=OpportunityOutcome.OUTCOME_MAYBE_LATER)
        self.assertEqual(action, OpportunitySuggestion.ACTION_REACTIVATE)

    def test_khach_da_tu_choi_thi_KHONG_kich_hoat_lai(self):
        """Chao lai nguoi da noi khong la cach nhanh nhat de mat khach."""
        self.assertNotIn(OpportunityOutcome.OUTCOME_NOT_INTERESTED,
                         OpportunityOutcome.REACTIVATABLE)
        self.assertNotIn(OpportunityOutcome.OUTCOME_ALREADY_USING,
                         OpportunityOutcome.REACTIVATABLE)


class SuggestionLifecycleTest(TestCase):
    """Vong doi de xuat: tao -> nhan/de sau/bo qua -> co hoi."""

    def setUp(self):
        self.rm = make_user("rm-suggest", roles.RB_SALES)
        self.an = Person.objects.create(display_name="Nguyen Van An",
                                        primary_phone="+84901234567")
        RBProfile.objects.create(person=self.an, occupation="Trưởng phòng kinh doanh")

    def _signal(self, excerpt="Em cần vay mua nhà", confidence=0.85, days_ago=0):
        return Signal.objects.create(
            person=self.an, domain="rb", signal_type="financial_need",
            source="facebook", confidence=confidence,
            evidence={"excerpt": excerpt, "reason": ""},
            observed_at=timezone.now() - timedelta(days=days_ago))

    def test_nhan_de_xuat_tao_dung_mot_co_hoi(self):
        made = suggestions.from_signal(self._signal())
        opportunity, created = suggestions.accept(made[0], actor=self.rm)
        self.assertTrue(created)
        self.assertEqual(opportunity.product, PRODUCT_MORTGAGE)
        self.assertEqual(opportunity.assigned_to, self.rm)
        self.assertEqual(opportunity.status, RBOpportunity.STATUS_ACCEPTED)

        made[0].refresh_from_db()
        self.assertEqual(made[0].status, OpportunitySuggestion.STATUS_CONVERTED)
        self.assertEqual(made[0].converted_opportunity_id, opportunity.pk)

    def test_nhan_KHONG_THE_thieu_nguoi_nhan(self):
        """Khong co duong nao de he thong tu nhan viec thay RM."""
        made = suggestions.from_signal(self._signal())
        with self.assertRaises(ValueError):
            suggestions.accept(made[0], actor=None)

    def test_hai_nguoi_nhan_cung_luc_khong_tao_co_hoi_trung(self):
        made = suggestions.from_signal(self._signal())
        khac = make_user("rm-khac", roles.RB_SALES)
        dau, tao_moi = suggestions.accept(made[0], actor=self.rm)
        sau, tao_lai = suggestions.accept(made[0], actor=khac)
        self.assertTrue(tao_moi)
        self.assertFalse(tao_lai)
        self.assertEqual(dau.pk, sau.pk)
        self.assertEqual(RBOpportunity.objects.count(), 1)

    def test_nhan_khi_da_co_co_hoi_dang_mo_thi_dung_lai_co_hoi_do(self):
        san_co = RBOpportunity.objects.create(person=self.an, product=PRODUCT_MORTGAGE,
                                              status=RBOpportunity.STATUS_ACCEPTED)
        made = suggestions.from_signal(self._signal())
        opportunity, created = suggestions.accept(made[0], actor=self.rm)
        self.assertFalse(created)
        self.assertEqual(opportunity.pk, san_co.pk)
        self.assertEqual(RBOpportunity.objects.count(), 1)

    def test_co_hoi_giu_lai_bang_chung_cua_de_xuat(self):
        """Sau tuan sau RM van phai tra loi duoc: vi sao toi nhan viec nay."""
        made = suggestions.from_signal(self._signal())
        opportunity, _ = suggestions.accept(made[0], actor=self.rm)
        self.assertTrue(opportunity.evidence.get("why"))
        self.assertEqual(opportunity.evidence.get("from_suggestion"), made[0].pk)

    def test_de_sau_thi_bien_khoi_danh_sach_nhung_khong_mat(self):
        made = suggestions.from_signal(self._signal())
        suggestions.snooze(made[0], actor=self.rm, days=14)
        self.assertNotIn(made[0].pk, [s.pk for s in suggestions.todays_best()])
        self.assertTrue(OpportunitySuggestion.objects.filter(pk=made[0].pk).exists())

    def test_de_sau_het_han_thi_quay_lai_danh_sach(self):
        made = suggestions.from_signal(self._signal())
        suggestions.snooze(made[0], actor=self.rm,
                           until=timezone.now() - timedelta(hours=1))
        self.assertIn(made[0].pk, [s.pk for s in suggestions.todays_best()])

    def test_tin_hieu_moi_danh_thuc_de_xuat_dang_ngu(self):
        """'De sau' khong duoc bien thanh 'bo qua vinh vien' ngoai y RM."""
        made = suggestions.from_signal(self._signal())
        suggestions.snooze(made[0], actor=self.rm, days=30)
        suggestions.from_signal(self._signal("Em vẫn đang tìm mua nhà"))
        made[0].refresh_from_db()
        self.assertEqual(made[0].status, OpportunitySuggestion.STATUS_NEW)

    def test_bo_qua_phai_co_ly_do(self):
        made = suggestions.from_signal(self._signal())
        suggestions.dismiss(made[0], actor=self.rm, reason="Khách đã mua nhà rồi")
        made[0].refresh_from_db()
        self.assertEqual(made[0].status, OpportunitySuggestion.STATUS_DISMISSED)
        self.assertIn(u"mua nhà", made[0].dismiss_reason)

    def test_de_xuat_bi_bo_qua_khong_con_trong_danh_sach(self):
        made = suggestions.from_signal(self._signal())
        suggestions.dismiss(made[0], actor=self.rm, reason="Sai nguoi")
        self.assertEqual(list(suggestions.todays_best()), [])

    def test_de_xuat_qua_han_thi_het_han(self):
        made = suggestions.from_signal(self._signal())
        OpportunitySuggestion.objects.filter(pk=made[0].pk).update(
            expires_at=timezone.now() - timedelta(days=1))
        suggestions.expire_stale()
        made[0].refresh_from_db()
        self.assertEqual(made[0].status, OpportunitySuggestion.STATUS_EXPIRED)

    def test_don_dep_chay_nhieu_lan_khong_doi_ket_qua(self):
        made = suggestions.from_signal(self._signal())
        OpportunitySuggestion.objects.filter(pk=made[0].pk).update(
            expires_at=timezone.now() - timedelta(days=1))
        self.assertEqual(suggestions.expire_stale(), 1)
        self.assertEqual(suggestions.expire_stale(), 0)

    def test_DNC_thi_khong_tao_de_xuat_nao(self):
        Relationship.objects.create(person=self.an, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        self.assertEqual(suggestions.from_signal(self._signal()), [])
        self.assertEqual(OpportunitySuggestion.objects.count(), 0)

    def test_chua_co_so_dien_thoai_van_tao_de_xuat(self):
        """Nguoi vua lo nhu cau tren mang xa hoi la nhom dang gia nhat."""
        chua_co_so = Person.objects.create(display_name="Chua co so")
        signal = Signal.objects.create(
            person=chua_co_so, domain="rb", signal_type="financial_need",
            source="facebook", confidence=0.9,
            evidence={"excerpt": "Em cần vay mua nhà"}, observed_at=timezone.now())
        made = suggestions.from_signal(signal)
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].recommended_action,
                         OpportunitySuggestion.ACTION_ASK_FOR_INFORMATION)

    def test_danh_sach_xep_theo_diem_uu_tien(self):
        suggestions.from_signal(self._signal("Em cần vay mua nhà"))
        suggestions.from_signal(self._signal("Em muốn gửi tiết kiệm"))
        rows = list(suggestions.todays_best())
        self.assertGreaterEqual(len(rows), 2)
        diem = [r.priority_score for r in rows]
        self.assertEqual(diem, sorted(diem, reverse=True))

    def test_tom_tat_dem_dung_cac_nhom(self):
        suggestions.from_signal(self._signal())
        tom_tat = suggestions.summarize(suggestions.todays_best())
        self.assertEqual(tom_tat["total"], 1)
        self.assertEqual(tom_tat["fresh_signals"], 1)

    def test_diem_tung_chieu_duoc_luu_rieng_khong_chi_luu_tong(self):
        """'Khop ho so nhung kho goi' va 'de goi nhung mo ho' la hai viec khac nhau."""
        made = suggestions.from_signal(self._signal())[0]
        for field in ("fit_score", "need_score", "timing_score",
                      "reachability_score", "value_score"):
            self.assertGreater(getattr(made, field), 0, field)
        self.assertEqual(
            made.priority_score,
            scoring.priority_score(made.fit_score, made.need_score, made.timing_score,
                                   made.reachability_score, made.value_score,
                                   strategic_weight=made.evidence["strategic_weight"]))

    def test_confidence_KHAC_priority(self):
        """Chac chan ve nhu cau va dang uu tien la hai cau hoi khac nhau."""
        made = suggestions.from_signal(self._signal())[0]
        self.assertLessEqual(made.confidence, 1.0)
        self.assertGreater(made.priority_score, 1.0)


class OutcomeTrackingTest(TestCase):
    """Khep vong lap: gui roi thi sao (Master Plan muc 35)."""

    def setUp(self):
        self.rm = make_user("rm-outcome", roles.RB_SALES)
        self.an = Person.objects.create(display_name="Nguyen Van An",
                                        primary_phone="+84901234567")
        self.opportunity = RBOpportunity.objects.create(
            person=self.an, product=PRODUCT_MORTGAGE, assigned_to=self.rm)

    def test_ghi_nhan_ket_qua(self):
        outcome = OpportunityOutcome.objects.create(
            opportunity=self.opportunity, person=self.an, channel="call",
            outcome=OpportunityOutcome.OUTCOME_INTERESTED, created_by=self.rm)
        self.assertEqual(self.opportunity.outcomes.count(), 1)
        self.assertEqual(outcome.created_by_name, str(self.rm))

    def test_ket_qua_cu_dan_toi_hanh_dong_kich_hoat_lai(self):
        OpportunityOutcome.objects.create(
            opportunity=self.opportunity, person=self.an,
            outcome=OpportunityOutcome.OUTCOME_MAYBE_LATER, created_by=self.rm)
        self.opportunity.status = RBOpportunity.STATUS_LOST
        self.opportunity.save(update_fields=["status"])

        signal = Signal.objects.create(
            person=self.an, domain="rb", signal_type="financial_need",
            source="facebook", confidence=0.9,
            evidence={"excerpt": "Em vẫn cần vay mua nhà"},
            observed_at=timezone.now())
        made = suggestions.from_signal(signal)
        self.assertEqual(made[0].recommended_action,
                         OpportunitySuggestion.ACTION_REACTIVATE)
        self.assertEqual(made[0].evidence["previous_outcome"],
                         OpportunityOutcome.OUTCOME_MAYBE_LATER)


class TodaysOpportunitiesApiTest(TestCase):
    """API "Cơ hội hôm nay" và các hành động của RM."""

    def setUp(self):
        self.rm = make_user("rm-api", roles.RB_SALES)
        self.client.force_login(self.rm)
        self.an = Person.objects.create(display_name="Nguyễn Văn An",
                                        primary_phone="+84901234567")
        RBProfile.objects.create(person=self.an, occupation="Trưởng phòng kinh doanh")
        signal = Signal.objects.create(
            person=self.an, domain="rb", signal_type="financial_need",
            source="facebook", confidence=0.9,
            evidence={"excerpt": u"Em cần vay mua nhà"}, observed_at=timezone.now())
        self.suggestion = suggestions.from_signal(signal)[0]

    def test_danh_sach_tra_ve_the_kem_ly_do(self):
        response = self.client.get(reverse("rb-today"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["summary"]["total"], 1)
        card = body["results"][0]
        self.assertTrue(card["why"], u"Thẻ không có VÌ SAO BÂY GIỜ là thẻ vô dụng")
        self.assertTrue(card["recommended_action"])
        self.assertIn("fit", card["scores"])
        self.assertGreater(card["priority_score"], 0)

    def test_nhan_co_hoi_tao_viec_cho_dung_nguoi_bam_nut(self):
        response = self.client.post(
            reverse("rb-suggestion-action", args=[self.suggestion.pk]),
            {"action": "accept"}, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        opportunity = RBOpportunity.objects.get()
        self.assertEqual(opportunity.assigned_to, self.rm)

    def test_nhan_hai_lan_thi_bao_da_xu_ly(self):
        url = reverse("rb-suggestion-action", args=[self.suggestion.pk])
        self.client.post(url, {"action": "accept"}, content_type="application/json")
        lai = self.client.post(url, {"action": "accept"},
                               content_type="application/json")
        self.assertEqual(lai.status_code, 409)
        self.assertEqual(RBOpportunity.objects.count(), 1)

    def test_bo_qua_KHONG_ly_do_bi_tu_choi(self):
        response = self.client.post(
            reverse("rb-suggestion-action", args=[self.suggestion.pk]),
            {"action": "dismiss"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.suggestion.refresh_from_db()
        self.assertEqual(self.suggestion.status, OpportunitySuggestion.STATUS_NEW)

    def test_bo_qua_co_ly_do_thi_duoc(self):
        response = self.client.post(
            reverse("rb-suggestion-action", args=[self.suggestion.pk]),
            {"action": "dismiss", "reason": u"Khách đã mua nhà"},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.suggestion.refresh_from_db()
        self.assertEqual(self.suggestion.status,
                         OpportunitySuggestion.STATUS_DISMISSED)

    def test_de_sau_nhan_so_ngay(self):
        response = self.client.post(
            reverse("rb-suggestion-action", args=[self.suggestion.pk]),
            {"action": "snooze", "days": 7}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.suggestion.refresh_from_db()
        self.assertEqual(self.suggestion.status, OpportunitySuggestion.STATUS_SNOOZED)
        self.assertIsNotNone(self.suggestion.snoozed_until)

    def test_hanh_dong_la_bi_tu_choi(self):
        response = self.client.post(
            reverse("rb-suggestion-action", args=[self.suggestion.pk]),
            {"action": "xoa-het"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_ghi_nhan_ket_qua_qua_API(self):
        self.client.post(reverse("rb-suggestion-action", args=[self.suggestion.pk]),
                         {"action": "accept"}, content_type="application/json")
        opportunity = RBOpportunity.objects.get()
        response = self.client.post(
            reverse("rb-opportunity-outcomes", args=[opportunity.pk]),
            {"outcome": "INTERESTED", "channel": "call", "note": u"Hẹn gọi lại"},
            content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(opportunity.outcomes.count(), 1)

    def test_ket_qua_la_bi_tu_choi(self):
        opportunity = RBOpportunity.objects.create(
            person=self.an, product=PRODUCT_MORTGAGE, assigned_to=self.rm)
        response = self.client.post(
            reverse("rb-opportunity-outcomes", args=[opportunity.pk]),
            {"outcome": "KHONG-CO-MA-NAY"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_khong_phu_trach_thi_khong_ghi_duoc_ket_qua(self):
        nguoi_khac = make_user("rm-ngoai", roles.RB_SALES)
        opportunity = RBOpportunity.objects.create(
            person=self.an, product=PRODUCT_MORTGAGE, assigned_to=nguoi_khac)
        response = self.client.post(
            reverse("rb-opportunity-outcomes", args=[opportunity.pk]),
            {"outcome": "REPLIED"}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_chua_dang_nhap_bi_chan(self):
        self.client.logout()
        self.assertIn(self.client.get(reverse("rb-today")).status_code, (401, 403))
