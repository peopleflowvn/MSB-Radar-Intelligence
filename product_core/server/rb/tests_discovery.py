# -*- coding: utf-8 -*-
"""Ba cơ chế giữ cho cá nhân hoá không bóp nghẹt việc săn khách.

Cá nhân hoá có một mặt trái dễ bỏ sót: càng khai kỹ, RM càng chỉ nhìn thấy thứ
họ đã biết mình muốn nhìn. Lời khai biến thành cái lồng, và Radar — vốn sinh ra
để *"phát hiện thứ người dùng không biết để đi tìm"* (Nguyên tắc 4) — biến thành
một cái bộ lọc.

Ba cơ chế chống lại điều đó, mỗi cái canh một kiểu hỏng khác nhau:

    Suất khám phá        cơ hội mạnh ngoài khai báo vẫn hiện ra
    Chuyển giao          cơ hội ngoài địa bàn được ĐỊNH TUYẾN, không bị đánh rơi
    Suy từ hành vi       form không bao giờ trống, kể cả khi RM không khai gì
"""
from accounts import roles
from accounts.models import UserWorkProfile
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from people.models import Person, Signal

from . import scoring, suggestions
from .models import (PRODUCT_MORTGAGE, PRODUCT_SAVINGS, OpportunityOutcome,
                     RBOpportunity)


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


def seed_suggestion(person, excerpt="Em cần vay mua nhà", confidence=0.9):
    signal = Signal.objects.create(
        person=person, domain="rb", signal_type="financial_need",
        source="facebook", confidence=confidence,
        evidence={"excerpt": excerpt}, observed_at=timezone.now())
    made = suggestions.from_signal(signal)
    return made[0] if made else None


class DiscoverySlotTest(TestCase):
    """Suất khám phá — giữ Nguyên tắc 4 khi đã bật cá nhân hoá."""

    def setUp(self):
        self.rm = make_user("rm-kham-pha", roles.RB_SALES)
        UserWorkProfile.objects.create(user=self.rm,
                                       domain=UserWorkProfile.DOMAIN_RB,
                                       regions=["Hà Nội"])

    def _fill(self, trong_dia_ban, ngoai_dia_ban):
        for index in range(trong_dia_ban):
            person = Person.objects.create(
                display_name="HN %d" % index, location="Hà Nội",
                primary_phone="+849011111%02d" % index)
            # Tín hiệu yếu hơn: đây là những cơ hội KHÁCH QUAN kém hơn, chỉ
            # được lên đầu nhờ cá nhân hoá.
            seed_suggestion(person, "Em muốn gửi tiết kiệm", confidence=0.6)
        for index in range(ngoai_dia_ban):
            person = Person.objects.create(
                display_name="DN %d" % index, location="Đà Nẵng",
                primary_phone="+849022222%02d" % index)
            seed_suggestion(person, "Em cần vay mua nhà", confidence=0.95)

    def test_co_hoi_manh_ngoai_khai_bao_van_hien_ra(self):
        """Không có suất khám phá thì cả 10 dòng đều là khách Hà Nội."""
        self._fill(trong_dia_ban=10, ngoai_dia_ban=5)
        rows = list(suggestions.todays_best(user=self.rm, limit=10))
        ngoai = [r for r in rows if r.territory == scoring.TERRITORY_OUT]
        self.assertTrue(ngoai, "Danh sách bịt kín khai báo là một cái bộ lọc, "
                               "không phải radar")

    def test_the_kham_pha_duoc_danh_dau_ro(self):
        """RM phải biết vì sao một thẻ ngoài địa bàn lại nằm trong danh sách."""
        self._fill(trong_dia_ban=10, ngoai_dia_ban=5)
        rows = list(suggestions.todays_best(user=self.rm, limit=10))
        self.assertTrue(any(r.is_discovery for r in rows))

    def test_suat_kham_pha_xep_theo_diem_KHACH_QUAN(self):
        """Xếp theo điểm cá nhân hoá thì nó chỉ là phần đuôi của cùng danh sách."""
        self._fill(trong_dia_ban=10, ngoai_dia_ban=5)
        rows = list(suggestions.todays_best(user=self.rm, limit=10))
        kham_pha = [r for r in rows if r.is_discovery]
        thuong = [r for r in rows if not r.is_discovery]
        self.assertTrue(kham_pha)
        # Cơ hội khám phá phải mạnh hơn về điểm gốc, nếu không thì vô nghĩa.
        self.assertGreater(max(r.priority_score for r in kham_pha),
                           min(r.priority_score for r in thuong))

    def test_du_lieu_it_hon_limit_thi_khong_cat_bot(self):
        self._fill(trong_dia_ban=2, ngoai_dia_ban=1)
        rows = list(suggestions.todays_best(user=self.rm, limit=10))
        self.assertEqual(len(rows), 3)

    def test_khong_khai_bao_thi_khong_can_suat_kham_pha(self):
        """Chưa khai gì thì cả danh sách vốn đã là điểm khách quan."""
        UserWorkProfile.objects.filter(user=self.rm).delete()
        self._fill(trong_dia_ban=3, ngoai_dia_ban=3)
        rows = list(suggestions.todays_best(user=self.rm, limit=5))
        self.assertEqual(len(rows), 5)
        self.assertFalse(any(getattr(r, "is_discovery", False) for r in rows))


class HandoffTest(TestCase):
    """Ngoài địa bàn thì ĐỊNH TUYẾN, không đánh rơi."""

    def setUp(self):
        self.hanoi_rm = make_user("rm-hn", roles.RB_SALES)
        self.danang_rm = make_user("rm-dn", roles.RB_SALES)
        UserWorkProfile.objects.create(user=self.hanoi_rm,
                                       domain=UserWorkProfile.DOMAIN_RB,
                                       regions=["Hà Nội"])
        UserWorkProfile.objects.create(user=self.danang_rm,
                                       domain=UserWorkProfile.DOMAIN_RB,
                                       regions=["Đà Nẵng"])
        self.khach_dn = Person.objects.create(display_name="Khách Đà Nẵng",
                                              location="Đà Nẵng",
                                              primary_phone="+84903333333")

    def test_phat_ngoai_dia_ban_phai_NHE(self):
        """Trừ nặng biến cơ hội cần định tuyến thành cơ hội bị đánh rơi."""
        self.assertGreaterEqual(scoring.MISS_REGION, -5.0)
        self.assertLess(scoring.MISS_REGION, 0)

    def test_goi_y_dung_RM_phu_trach_khu_vuc(self):
        seed_suggestion(self.khach_dn)
        rows = list(suggestions.todays_best(user=self.hanoi_rm, limit=10))
        row = next(r for r in rows if r.person_id == self.khach_dn.pk)
        self.assertEqual(row.territory, scoring.TERRITORY_OUT)
        self.assertIsNotNone(row.handoff_to)
        self.assertEqual(row.handoff_to["user_id"], self.danang_rm.pk)

    def test_khong_ai_phu_trach_thi_khong_bia_ra_nguoi(self):
        UserWorkProfile.objects.filter(user=self.danang_rm).delete()
        seed_suggestion(self.khach_dn)
        rows = list(suggestions.todays_best(user=self.hanoi_rm, limit=10))
        row = next(r for r in rows if r.person_id == self.khach_dn.pk)
        self.assertIsNone(row.handoff_to)

    def test_khong_goi_y_chuyen_cho_chinh_minh(self):
        khach_hn = Person.objects.create(display_name="Khách HN",
                                         location="Hà Nội",
                                         primary_phone="+84904444444")
        seed_suggestion(khach_hn)
        rows = list(suggestions.todays_best(user=self.hanoi_rm, limit=10))
        row = next(r for r in rows if r.person_id == khach_hn.pk)
        self.assertEqual(row.territory, scoring.TERRITORY_IN)
        self.assertIsNone(row.handoff_to)

    def test_API_tra_ve_goi_y_chuyen_giao(self):
        seed_suggestion(self.khach_dn)
        self.client.force_login(self.hanoi_rm)
        results = self.client.get(reverse("rb-today")).json()["results"]
        card = next(r for r in results if r["person"] == self.khach_dn.pk)
        self.assertEqual(card["territory"], "out")
        self.assertEqual(card["handoff_to"]["user_id"], self.danang_rm.pk)


class ObservedProfileTest(TestCase):
    """Suy khai báo từ hành vi thật — để form không bao giờ trống."""

    def setUp(self):
        self.rm = make_user("rm-quan-sat", roles.RB_SALES)

    def _opportunity(self, location, product=PRODUCT_MORTGAGE, index=0):
        person = Person.objects.create(
            display_name="Khách %s %d" % (location, index),
            location=location, primary_phone="+8490555%04d" % index)
        return RBOpportunity.objects.create(person=person, product=product,
                                            assigned_to=self.rm)

    def test_it_du_lieu_qua_thi_IM_LANG(self):
        """Đoán địa bàn từ hai cơ hội rồi điền sẵn là cách mất niềm tin nhanh nhất."""
        self._opportunity("Hà Nội", index=1)
        observed = suggestions.observed_work_profile(self.rm)
        self.assertFalse(observed["confident"])
        self.assertEqual(observed["regions"], [])

    def test_suy_ra_dia_ban_tu_viec_da_lam(self):
        for index in range(5):
            self._opportunity("Hà Nội", index=index)
        observed = suggestions.observed_work_profile(self.rm)
        self.assertTrue(observed["confident"])
        self.assertIn("Hà Nội", observed["regions"])
        self.assertIn(PRODUCT_MORTGAGE, observed["focus_products"])

    def test_mot_co_hoi_le_KHONG_thanh_dia_ban(self):
        for index in range(9):
            self._opportunity("Hà Nội", index=index)
        self._opportunity("Cần Thơ", index=99)
        observed = suggestions.observed_work_profile(self.rm)
        self.assertIn("Hà Nội", observed["regions"])
        self.assertNotIn("Cần Thơ", observed["regions"])

    def test_san_pham_CHOT_DUOC_duoc_uu_tien_hon(self):
        """Nhận 20 cơ hội thẻ mà chỉ chốt được bảo hiểm thì trọng tâm là bảo hiểm."""
        for index in range(6):
            self._opportunity("Hà Nội", product=PRODUCT_MORTGAGE, index=index)
        for index in range(4):
            opportunity = self._opportunity("Hà Nội", product=PRODUCT_SAVINGS,
                                            index=100 + index)
            OpportunityOutcome.objects.create(
                opportunity=opportunity, person=opportunity.person,
                outcome=OpportunityOutcome.OUTCOME_CONVERTED, created_by=self.rm)
        observed = suggestions.observed_work_profile(self.rm)
        self.assertEqual(observed["focus_products"][0], PRODUCT_SAVINGS)

    def test_KHONG_tu_luu_vao_khai_bao(self):
        """Máy quan sát và đề xuất; người xác nhận."""
        for index in range(5):
            self._opportunity("Hà Nội", index=index)
        suggestions.observed_work_profile(self.rm)
        self.assertFalse(UserWorkProfile.objects.filter(user=self.rm).exists())

    def test_API_tra_ve_quan_sat_RIENG_khoi_khai_bao(self):
        """Người dùng phải phân biệt được đâu là mình khai, đâu là máy đoán."""
        for index in range(5):
            self._opportunity("Hà Nội", index=index)
        self.client.force_login(self.rm)
        body = self.client.get(reverse("rb-work-profile")).json()
        self.assertEqual(body["regions"], [])
        self.assertIn("Hà Nội", body["observed"]["regions"])
        self.assertTrue(body["observed"]["confident"])


class CapacityTest(TestCase):
    """`daily_capacity` phải có tác dụng thật, không phải trường trang trí."""

    def setUp(self):
        self.rm = make_user("rm-capacity", roles.RB_SALES)
        self.client.force_login(self.rm)
        for index in range(12):
            person = Person.objects.create(display_name="Khách %d" % index,
                                           primary_phone="+8490777%04d" % index)
            seed_suggestion(person)

    def test_so_dong_mac_dinh_theo_khai_bao(self):
        UserWorkProfile.objects.create(user=self.rm,
                                       domain=UserWorkProfile.DOMAIN_RB,
                                       daily_capacity=5)
        results = self.client.get(reverse("rb-today")).json()["results"]
        self.assertEqual(len(results), 5)

    def test_van_xem_them_duoc_khi_muon(self):
        """Chặn RM xem thêm là quyết định của tổ chức, không phải của một trường."""
        UserWorkProfile.objects.create(user=self.rm,
                                       domain=UserWorkProfile.DOMAIN_RB,
                                       daily_capacity=5)
        results = self.client.get(reverse("rb-today"), {"limit": 12}).json()["results"]
        self.assertEqual(len(results), 12)
