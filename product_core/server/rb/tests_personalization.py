# -*- coding: utf-8 -*-
"""Cá nhân hoá đề xuất theo khai báo của RM, và các lỗi truy vấn liên quan.

Bài canh kỹ nhất ở đây là `test_KHONG_ghi_de_diem_goc`. Điểm lưu trong
`OpportunitySuggestion` phải giữ nghĩa khách quan; nếu nó pha sở thích người
xem thì:

  • tỷ lệ chấp nhận của RM A và RM B không còn so được với nhau;
  • câu hỏi "vì sao đề xuất này 82 điểm" không còn một câu trả lời duy nhất;
  • RM sửa địa bàn hôm nay sẽ viết lại điểm của những đề xuất sinh tháng trước.
"""
from accounts import roles
from accounts.models import UserWorkProfile
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from people.models import Person, Signal

from . import scoring, suggestions
from .models import PRODUCT_MORTGAGE


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class PersonalizationTest(TestCase):
    """Cơ hội tốt và cơ hội tốt **cho tôi** là hai câu hỏi khác nhau."""

    def setUp(self):
        self.rm = make_user("rm-canhan", roles.RB_SALES)
        self.hanoi = Person.objects.create(display_name="Khách Hà Nội",
                                           primary_phone="+84901234567",
                                           location="Hà Nội")
        self.danang = Person.objects.create(display_name="Khách Đà Nẵng",
                                            primary_phone="+84901234568",
                                            location="Đà Nẵng")

    def _profile(self, **kwargs):
        return UserWorkProfile.objects.create(
            user=self.rm, domain=UserWorkProfile.DOMAIN_RB, **kwargs)

    def _suggest(self, person, excerpt="Em cần vay mua nhà"):
        signal = Signal.objects.create(
            person=person, domain="rb", signal_type="financial_need",
            source="facebook", confidence=0.9,
            evidence={"excerpt": excerpt}, observed_at=timezone.now())
        return suggestions.from_signal(signal)[0]

    def test_chua_khai_bao_thi_dung_nguyen_diem_goc(self):
        """Hệ thống phải dùng được ngay khi chưa ai điền form nào."""
        suggestion = self._suggest(self.hanoi)
        diem, why = scoring.personalize(suggestion, None)
        self.assertEqual(diem, suggestion.priority_score)
        self.assertEqual(why, [])

    def test_KHONG_ghi_de_diem_goc(self):
        """Cá nhân hoá trả điểm mới, không sửa thứ đã lưu trong CSDL."""
        suggestion = self._suggest(self.hanoi)
        goc = suggestion.priority_score
        profile = self._profile(regions=["Hà Nội"], focus_products=[PRODUCT_MORTGAGE])
        scoring.personalize(suggestion, profile)
        suggestion.refresh_from_db()
        self.assertEqual(suggestion.priority_score, goc)

    def test_dung_dia_ban_thi_duoc_cong_diem(self):
        suggestion = self._suggest(self.hanoi)
        profile = self._profile(regions=["Hà Nội"])
        diem, why = scoring.personalize(suggestion, profile)
        self.assertGreater(diem, suggestion.priority_score)
        self.assertIn("địa bàn", " ".join(why))

    def test_ngoai_dia_ban_thi_bi_tru_diem(self):
        suggestion = self._suggest(self.danang)
        profile = self._profile(regions=["Hà Nội"])
        diem, why = scoring.personalize(suggestion, profile)
        self.assertLess(diem, suggestion.priority_score)
        self.assertIn("Ngoài địa bàn", " ".join(why))

    def test_khong_ro_khu_vuc_thi_KHONG_bi_phat(self):
        """Thiếu dữ liệu là lỗi hệ thống, không phải bằng chứng chống lại khách."""
        khong_ro = Person.objects.create(display_name="Không rõ nơi ở",
                                         primary_phone="+84901234569")
        suggestion = self._suggest(khong_ro)
        profile = self._profile(regions=["Hà Nội"])
        diem, why = scoring.personalize(suggestion, profile)
        self.assertEqual(diem, suggestion.priority_score)
        self.assertIn("Chưa rõ khu vực", " ".join(why))

    def test_khop_dia_ban_bo_dau_va_khong_dau(self):
        """'Hà Nội' phải khớp 'ha noi' — người khai không nên phải gõ đúng dấu."""
        khach = Person.objects.create(display_name="Khách", location="ha noi",
                                      primary_phone="+84901234570")
        suggestion = self._suggest(khach)
        profile = self._profile(regions=["Hà Nội"])
        diem, _why = scoring.personalize(suggestion, profile)
        self.assertGreater(diem, suggestion.priority_score)

    def test_khop_dia_ban_khac_bi_danh(self):
        """RM khai địa bàn 'TP.HCM', khách ghi 'Hồ Chí Minh' — phải khớp,
        đúng cách bộ lọc tìm kiếm đã đối chiếu địa danh (core/vn_locations.py).
        Trước đây chỉ bỏ dấu/viết thường nên hai cách viết này khớp trượt."""
        khach = Person.objects.create(display_name="Khách Sài Gòn",
                                      location="Hồ Chí Minh",
                                      primary_phone="+84901234571")
        suggestion = self._suggest(khach)
        profile = self._profile(regions=["TP.HCM"])
        diem, why = scoring.personalize(suggestion, profile)
        self.assertGreater(diem, suggestion.priority_score)
        self.assertIn("địa bàn", " ".join(why))

    def test_dung_san_pham_trong_tam_thi_len_hang(self):
        suggestion = self._suggest(self.hanoi)
        profile = self._profile(focus_products=[PRODUCT_MORTGAGE])
        diem, why = scoring.personalize(suggestion, profile)
        self.assertGreater(diem, suggestion.priority_score)
        self.assertIn("sản phẩm bạn đang phụ trách", " ".join(why))

    def test_ca_nhan_hoa_bi_gioi_han_khong_lat_nguoc_chat_luong(self):
        """Trúng chỉ tiêu không được đẩy cơ hội yếu lên trên cơ hội mạnh."""
        suggestion = self._suggest(self.hanoi)
        profile = self._profile(regions=["Hà Nội"],
                                focus_products=[PRODUCT_MORTGAGE],
                                target_segments=["priority"])
        diem, _why = scoring.personalize(suggestion, profile)
        self.assertLessEqual(diem - suggestion.priority_score,
                             scoring.PERSONALIZATION_CAP)

    def test_danh_sach_xep_lai_theo_khai_bao(self):
        """Cơ hội trúng địa bàn phải nổi lên trong danh sách của riêng RM đó."""
        self._suggest(self.danang, "Em cần vay mua nhà")
        self._suggest(self.hanoi, "Em muốn gửi tiết kiệm")
        self._profile(regions=["Hà Nội"])
        rows = list(suggestions.todays_best(user=self.rm, limit=10))
        self.assertEqual(rows[0].person_id, self.hanoi.pk)

    def test_ghi_chu_tu_do_KHONG_doi_diem(self):
        """Văn bản tự do chỉ để AI diễn giải, không được lái thứ hạng."""
        suggestion = self._suggest(self.hanoi)
        profile = self._profile(notes="Tôi chuyên khách VIP, ưu tiên mọi thứ")
        diem, _why = scoring.personalize(suggestion, profile)
        self.assertEqual(diem, suggestion.priority_score)


class WorkProfileApiTest(TestCase):
    def setUp(self):
        self.rm = make_user("rm-profile-api", roles.RB_SALES)
        self.client.force_login(self.rm)

    def test_lan_dau_mo_thi_tao_ho_so_rong(self):
        response = self.client.get(reverse("rb-work-profile"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["regions"], [])
        self.assertEqual(response.json()["domain"], "rb")

    def test_luu_khai_bao(self):
        response = self.client.put(
            reverse("rb-work-profile"),
            {"regions": ["Hà Nội", "Bắc Ninh"],
             "focus_products": [PRODUCT_MORTGAGE],
             "target_segments": ["priority"],
             "daily_capacity": 15,
             "notes": "Phụ trách khu công nghiệp phía Bắc"},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["regions"], ["Hà Nội", "Bắc Ninh"])
        self.assertEqual(body["daily_capacity"], 15)

    def test_san_pham_khong_co_that_bi_tu_choi(self):
        response = self.client.put(
            reverse("rb-work-profile"),
            {"focus_products": ["san-pham-khong-ton-tai"]},
            content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_khong_phai_danh_sach_thi_bi_tu_choi(self):
        response = self.client.put(reverse("rb-work-profile"),
                                   {"regions": "Hà Nội"},
                                   content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_bo_trung_lap_va_khoang_trang(self):
        response = self.client.put(
            reverse("rb-work-profile"),
            {"regions": ["Hà Nội", "Hà Nội", "  ", ""]},
            content_type="application/json")
        self.assertEqual(response.json()["regions"], ["Hà Nội"])

    def test_chi_doc_duoc_ho_so_cua_chinh_minh(self):
        """Địa bàn và chỉ tiêu của một RM không phải thứ để RM khác dò."""
        nguoi_khac = make_user("rm-nguoi-khac", roles.RB_SALES)
        UserWorkProfile.objects.create(user=nguoi_khac,
                                       domain=UserWorkProfile.DOMAIN_RB,
                                       regions=["Đà Nẵng"])
        response = self.client.get(reverse("rb-work-profile"))
        self.assertEqual(response.json()["regions"], [])
        self.assertEqual(UserWorkProfile.objects.filter(user=nguoi_khac).count(), 1)

    def test_khong_doi_duoc_domain_qua_API(self):
        self.client.put(reverse("rb-work-profile"), {"domain": "talent"},
                        content_type="application/json")
        profile = UserWorkProfile.objects.get(user=self.rm)
        self.assertEqual(profile.domain, UserWorkProfile.DOMAIN_RB)

    def test_the_de_xuat_tra_ve_ca_hai_diem(self):
        person = Person.objects.create(display_name="Khách", location="Hà Nội",
                                       primary_phone="+84901234567")
        signal = Signal.objects.create(
            person=person, domain="rb", signal_type="financial_need",
            source="facebook", confidence=0.9,
            evidence={"excerpt": "Em cần vay mua nhà"}, observed_at=timezone.now())
        suggestions.from_signal(signal)
        UserWorkProfile.objects.create(user=self.rm,
                                       domain=UserWorkProfile.DOMAIN_RB,
                                       regions=["Hà Nội"])
        card = self.client.get(reverse("rb-today")).json()["results"][0]
        self.assertIn("priority_score", card)
        self.assertIn("personalized_score", card)
        self.assertGreater(card["personalized_score"], card["priority_score"])
        self.assertTrue(card["personalized_why"])


class TodaysListQueryTest(TestCase):
    """Lọc phải nằm trong truy vấn, không phải trên kết quả đã cắt."""

    def setUp(self):
        self.rm = make_user("rm-loc", roles.RB_SALES)
        self.client.force_login(self.rm)

    def test_loc_san_pham_khong_bi_cat_mat_boi_limit(self):
        """Lọc sau khi cắt `limit` trả về vài dòng dù còn nhiều dòng đúng."""
        for index in range(6):
            person = Person.objects.create(display_name="Khách %d" % index,
                                           primary_phone="+8490123456%d" % index)
            Signal.objects.create(
                person=person, domain="rb", signal_type="financial_need",
                source="facebook", confidence=0.9,
                evidence={"excerpt": "Em muốn gửi tiết kiệm"},
                observed_at=timezone.now())
        for index in range(3):
            person = Person.objects.create(display_name="Vay %d" % index,
                                           primary_phone="+8490987654%d" % index)
            Signal.objects.create(
                person=person, domain="rb", signal_type="financial_need",
                source="facebook", confidence=0.6,
                evidence={"excerpt": "Em cần vay mua nhà"},
                observed_at=timezone.now())
        for signal in Signal.objects.all():
            suggestions.from_signal(signal)

        response = self.client.get(reverse("rb-today"),
                                   {"product": PRODUCT_MORTGAGE, "limit": 2})
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        self.assertTrue(all(row["product"] == PRODUCT_MORTGAGE for row in results))

    def test_san_pham_khong_hop_le_bi_tu_choi(self):
        response = self.client.get(reverse("rb-today"), {"product": "khong-co"})
        self.assertEqual(response.status_code, 400)
