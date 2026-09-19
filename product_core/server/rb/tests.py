# -*- coding: utf-8 -*-
"""RB Radar — Phase 12, và chỗ Social Radar nối vào (Phase 13).

Hai điều bài này canh kỹ nhất:

1. **Không chép dữ liệu người sang cơ sở dữ liệu thứ hai.** Đó là Nguyên tắc 2,
   và cũng là lý do cả dự án tồn tại. Vi phạm nó thì RB Radar trở thành đúng cái
   vấn đề mà nó sinh ra để giải.
2. **Không gợi ý sản phẩm MSB không bán**, và không biến một câu nói thoáng qua
   thành một cuộc gọi chào hàng.
"""
import json
from datetime import timedelta
from unittest import mock

from accounts import roles
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import WorkflowStage
from people.models import Interaction, Person, Relationship, Signal
from talent.models import Pool

from . import routing
from .models import (PRODUCT_CREDIT_CARD, PRODUCT_FX, PRODUCT_INSURANCE,
                     PRODUCT_MORTGAGE, PRODUCT_SAVINGS, OpportunitySuggestion,
                     ProductInterest, RBOpportunity, RBOpportunityStatusEvent,
                     RBProfile)


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class SuggestProductTest(TestCase):
    def test_nhan_ra_nhu_cau_mua_nha(self):
        rows = routing.suggest_products("Nhà em đang cần vay 500 triệu mua nhà")
        self.assertEqual(rows[0].product, PRODUCT_MORTGAGE)
        self.assertIn("mua nhà", rows[0].matched)

    def test_nhu_cau_noi_bang_LOI_CUA_KHACH(self):
        """"Vay mua nhà" là tên sản phẩm; "đang tính mua nhà" là điều khách nói."""
        rows = routing.suggest_products("vay mua nhà")
        self.assertIn("mua", rows[0].need.lower())
        self.assertNotEqual(rows[0].need, "Vay mua nhà")

    def test_di_nuoc_ngoai_keo_theo_the_va_bao_hiem(self):
        """Đúng ví dụ Master Plan mục 32: "Sắp đi Nhật, nên đổi tiền hay dùng thẻ?"."""
        rows = routing.suggest_products("Sắp đi Nhật, nên đổi tiền hay dùng thẻ?")
        products = {row.product for row in rows}
        self.assertIn(PRODUCT_FX, products)
        self.assertTrue({PRODUCT_CREDIT_CARD, PRODUCT_INSURANCE} & products)

    def test_san_pham_suy_ra_thi_tin_cay_THAP_HON(self):
        rows = routing.suggest_products("Sắp đi Nhật, cần đổi tiền")
        theo = {row.product: row for row in rows}
        if PRODUCT_CREDIT_CARD in theo:
            self.assertLess(theo[PRODUCT_CREDIT_CARD].confidence,
                            theo[PRODUCT_FX].confidence)
            self.assertIn("suy ra", theo[PRODUCT_CREDIT_CARD].matched[0])

    def test_khong_khop_thi_KHONG_goi_y_bua(self):
        """Gợi ý bừa còn tệ hơn không gợi ý — RM sẽ ngừng tin cả danh sách."""
        self.assertEqual(routing.suggest_products("Hôm nay trời đẹp quá"), [])

    def test_toi_da_ba_nhom_san_pham(self):
        """Gợi ý sáu thứ cùng lúc thì RM không biết bắt đầu từ đâu."""
        rows = routing.suggest_products(
            "Em cần vay mua nhà, mua xe, mở thẻ tín dụng, gửi tiết kiệm, "
            "mua bảo hiểm và đầu tư chứng chỉ quỹ")
        self.assertLessEqual(len(rows), routing.MAX_PRODUCTS)

    def test_khong_chac_hon_tin_hieu_goc(self):
        rows = routing.suggest_products("vay mua nhà", base_confidence=0.4)
        self.assertLessEqual(rows[0].confidence, 0.6)


class ProfileTest(TestCase):
    def setUp(self):
        self.an = Person.objects.create(display_name="Nguyễn Văn An",
                                        primary_phone="+84901234567",
                                        primary_email="an@x.vn")

    def test_KHONG_chep_du_lieu_nguoi_sang_ho_so_ban_le(self):
        """Nguyên tắc 2. Chép sang là tự tay tạo ra bài toán mà dự án này giải."""
        routing.profile_for(self.an)
        truong = {f.name for f in RBProfile._meta.get_fields()}
        for cam in ("display_name", "full_name", "email", "phone",
                    "primary_email", "primary_phone"):
            self.assertNotIn(cam, truong)

    def test_lien_he_doc_tu_Person_va_da_che(self):
        """Vẫn đọc từ `Person` (không chép sang RBProfile), nhưng đã che."""
        routing.profile_for(self.an)
        self.client.force_login(make_user("sales", roles.RB_SALES))
        body = self.client.get(reverse("rb-profile", args=[self.an.pk])).json()
        self.assertEqual(body["primary_phone"], "+84******567")
        self.assertTrue(body["contact_masked"])
        self.assertEqual(body["display_name"], "Nguyễn Văn An")

    def test_cung_mot_Person_co_ca_hai_goc_nhin(self):
        """Một People Database, nhiều nghiệp vụ — đây là chỗ nó thành code."""
        from talent.models import TalentProfile
        TalentProfile.objects.create(person=self.an, current_title="Data Analyst")
        routing.profile_for(self.an)

        self.an.refresh_from_db()
        self.assertEqual(self.an.talent_profile.current_title, "Data Analyst")
        self.assertEqual(self.an.rb_profile.lead_status, RBProfile.LEAD_COLD)

    def test_ho_so_rong_van_tao_duoc(self):
        """RM cần chỗ để ghi ghi chú đầu tiên, không cần một trang 404."""
        self.client.force_login(make_user("sales", roles.RB_SALES))
        response = self.client.get(reverse("rb-profile", args=[self.an.pk]))
        self.assertEqual(response.status_code, 200)

    def test_cap_nhat_ho_so_dong_bo_quan_he_khach_hang(self):
        rm = make_user("sales-update", roles.RB_SALES)
        self.client.force_login(rm)
        response = self.client.patch(
            reverse("rb-profile-update", args=[self.an.pk]),
            data=json.dumps({
                "lead_status": "interested", "sales_owner_id": rm.pk,
                "interest_level": 5, "preferred_channel": "phone",
                "relationship_reason": "Quan tâm mua nhà",
                "relationship_notes": "Ưu tiên gọi buổi tối",
                "do_not_contact": True,
            }), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        relation = Relationship.objects.get(person=self.an, domain="rb")
        self.assertEqual(relation.state, "interested")
        self.assertEqual(relation.owner_user, rm)
        self.assertEqual(relation.interest_level, 5)
        self.assertTrue(relation.do_not_contact)
        self.assertEqual(response.json()["relationship_notes"], "Ưu tiên gọi buổi tối")

    def test_quan_he_khach_hang_den_han_chi_hien_cua_RM_va_khong_DNC(self):
        rm = make_user("sales-followup", roles.RB_SALES)
        self.client.force_login(rm)
        relation = Relationship.objects.create(
            person=self.an, domain="rb", state="warm", owner_user=rm,
            next_action="Gọi xác nhận", next_action_at=timezone.now())
        body = self.client.get(reverse("rb-relationship-followups")).json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["next_action"], "Gọi xác nhận")
        relation.do_not_contact = True
        relation.save()
        self.assertEqual(
            self.client.get(reverse("rb-relationship-followups")).json()["count"], 0)


class InterestTest(TestCase):
    def setUp(self):
        self.an = Person.objects.create(display_name="Nguyễn Văn An")

    def _record(self, text, confidence=0.6):
        rows = routing.suggest_products(text, base_confidence=confidence)
        return routing.record_interests(self.an, rows, source="social")

    def test_ghi_nhan_quan_tam(self):
        self._record("Em cần vay mua nhà")
        self.assertTrue(ProductInterest.objects.filter(
            product=PRODUCT_MORTGAGE).exists())

    def test_chi_NANG_muc_tin_cay_khong_ha(self):
        """Một bài mới nhắc thoáng qua không được xoá bằng chứng mạnh hơn."""
        self._record("Em cần vay mua nhà, mua chung cư, xây nhà", confidence=0.9)
        cao = ProductInterest.objects.get(product=PRODUCT_MORTGAGE).confidence

        self._record("nhắc qua mua nhà", confidence=0.3)
        self.assertEqual(
            ProductInterest.objects.get(product=PRODUCT_MORTGAGE).confidence, cao)

    def test_khong_tao_ban_ghi_trung(self):
        for _ in range(3):
            self._record("Em cần vay mua nhà")
        self.assertEqual(ProductInterest.objects.filter(
            product=PRODUCT_MORTGAGE).count(), 1)


class RouteSignalTest(TestCase):
    """Chỗ Social Radar nối vào RB Radar.

    Trước Phase 12, tín hiệu `rb` sinh ra rồi nằm im vì không nghiệp vụ nào nhận.

    **Đổi hợp đồng (Master Plan mục 33):** `route_signal()` giờ trả
    `OpportunitySuggestion`, không còn trả `RBOpportunity`. Ý nghĩa từng bài
    dưới đây giữ nguyên — chỉ đổi thứ được kiểm — vì nguyên tắc nghiệp vụ không
    đổi: không biến một câu nói thoáng qua thành một cuộc gọi chào hàng.
    """

    def setUp(self):
        self.an = Person.objects.create(display_name="Nguyễn Văn An",
                                        primary_phone="+84901234567")

    def _signal(self, excerpt, confidence=0.85):
        return Signal.objects.create(
            person=self.an, domain="rb", signal_type="financial_need",
            source="facebook", confidence=confidence,
            evidence={"excerpt": excerpt, "reason": ""},
            observed_at=timezone.now())

    def test_tin_hieu_thanh_de_xuat_chu_KHONG_thanh_co_hoi(self):
        """Ranh giới quan trọng nhất: máy đề xuất, người quyết định."""
        made = routing.route_signal(self._signal("Nhà em cần vay 500 triệu mua nhà"))
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].product, PRODUCT_MORTGAGE)
        self.assertEqual(made[0].status, OpportunitySuggestion.STATUS_NEW)
        # Chưa ai nhận thì hộp thư cơ hội của RM phải còn trống.
        self.assertEqual(RBOpportunity.objects.count(), 0)

    def test_de_xuat_LUON_kem_bang_chung_va_viec_nen_lam(self):
        """Nguyên tắc 4: không có bằng chứng thì không giải thích được."""
        made = routing.route_signal(self._signal("Em muốn gửi tiết kiệm kỳ hạn dài"))
        self.assertEqual(made[0].product, PRODUCT_SAVINGS)
        self.assertTrue(made[0].evidence["why"])
        self.assertTrue(made[0].recommended_action)
        self.assertIn("tiết kiệm", " ".join(made[0].evidence["why"]).lower())

    def test_tin_hieu_yeu_van_la_mot_co_hoi_nho_nhung_hanh_dong_phai_nhe_tay(self):
        """Dù nhỏ nhất, một tín hiệu có thật vẫn phải thành cơ hội (Radar không
        được lặng lẽ nuốt mất nó) — nhưng hành động đề xuất phải tương xứng:
        nhắc thoáng qua thì đi xin thêm thông tin, không phải gọi ngay chào
        vay tiền."""
        made = routing.route_signal(
            self._signal("có nhắc tới vay tiền", confidence=0.3))
        self.assertEqual(len(made), 1)
        self.assertEqual(OpportunitySuggestion.objects.count(), 1)
        self.assertLess(made[0].need_score, 50)
        self.assertNotEqual(made[0].recommended_action,
                            OpportunitySuggestion.ACTION_CALL_NOW)

    def test_khong_khop_san_pham_thi_khong_tao_gi(self):
        self.assertEqual(routing.route_signal(self._signal("trời hôm nay đẹp")), [])

    def test_khong_tao_de_xuat_trung_khi_dang_cho(self):
        """Người hay đăng bài không được chiếm hết màn hình của RM."""
        for _ in range(3):
            routing.route_signal(self._signal("Em cần vay mua nhà"))
        self.assertEqual(OpportunitySuggestion.objects.filter(
            product=PRODUCT_MORTGAGE).count(), 1)

    def test_tin_hieu_moi_lam_de_xuat_cu_manh_len(self):
        """Tín hiệu thứ hai phải nâng cái đang có, không xếp chồng thêm dòng."""
        routing.route_signal(self._signal("Em cần vay mua nhà", confidence=0.6))
        truoc = OpportunitySuggestion.objects.get(product=PRODUCT_MORTGAGE)
        diem_truoc = truoc.need_score

        routing.route_signal(self._signal("Em cần vay mua nhà gấp", confidence=0.95))
        sau = OpportunitySuggestion.objects.get(product=PRODUCT_MORTGAGE)
        self.assertGreater(sau.need_score, diem_truoc)
        self.assertEqual(OpportunitySuggestion.objects.count(), 1)
        self.assertEqual(sau.source_signals.count(), 2)


class OpportunityApiTest(TestCase):
    def setUp(self):
        self.rm = make_user("sales", roles.RB_SALES)
        self.client.force_login(self.rm)
        self.an = Person.objects.create(display_name="Nguyễn Văn An",
                                        primary_phone="+84901234567")
        self.opportunity = RBOpportunity.objects.create(
            person=self.an, product=PRODUCT_MORTGAGE, need="Đang tính mua nhà",
            confidence=0.8, suggested_action="Gọi hỏi kế hoạch mua nhà.")

    def _patch(self, body):
        return self.client.patch(
            reverse("rb-opportunity", args=[self.opportunity.pk]),
            data=json.dumps(body), content_type="application/json")

    def test_hop_thu_co_hoi(self):
        body = self.client.get(reverse("rb-opportunities"), {"open": "1"}).json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["product_label"], "Vay mua nhà")

    def test_lien_he_trong_danh_sach_DA_CHE(self):
        """Master Plan mục 27: danh sách không bao giờ trả liên hệ đầy đủ."""
        body = self.client.get(reverse("rb-opportunities")).json()
        row = body["results"][0]
        self.assertNotEqual(row["primary_phone"], "+84901234567")
        self.assertEqual(row["primary_phone"], "+84******567")
        self.assertTrue(row["contact_masked"])

    def test_nhan_viec_thi_tu_dung_ten(self):
        self._patch({"status": "accepted"})
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.assigned_to, self.rm)

    def test_dong_khong_thanh_BAT_BUOC_co_ly_do(self):
        """Đóng im lặng thì tháng sau hệ thống đề xuất lại, và khách nhận đúng
        lời chào đã từ chối."""
        response = self._patch({"status": "lost"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("lý do", response.json()["detail"])

    def test_dong_kem_ly_do_thi_duoc(self):
        response = self._patch({"status": "lost",
                                "close_reason": "Đã vay ngân hàng khác"})
        self.assertEqual(response.status_code, 200)

    def test_doi_trang_thai_cap_nhat_ho_so_khach(self):
        """Không đồng bộ thì hai RM cùng gọi một người trong một tuần."""
        self._patch({"status": "contacting"})
        profile = RBProfile.objects.get(person=self.an)
        self.assertEqual(profile.lead_status, RBProfile.LEAD_INTERESTED)
        self.assertIsNotNone(profile.last_contact_at)
        self.assertEqual(profile.sales_owner, self.rm)

    def test_de_lai_dau_vet_tren_timeline(self):
        self._patch({"status": "won"})
        self.assertTrue(Interaction.objects.filter(
            person=self.an, action="rb_won", domain="rb").exists())

    def test_trang_thai_la_thi_400(self):
        self.assertEqual(self._patch({"status": "linh_tinh"}).status_code, 400)

    def test_pipeline_tat_buoc_thi_khong_chuyen_duoc(self):
        WorkflowStage.objects.create(domain="rb", code="won", label="Thành công",
                                     is_active=False)
        response = self._patch({"status": "won"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("đang bị tắt", response.json()["detail"])

    def test_pipeline_chan_chuyen_tat_khi_da_cau_hinh(self):
        WorkflowStage.objects.create(domain="rb", code="new", label="Mới",
                                     allowed_next=["accepted"])
        WorkflowStage.objects.create(domain="rb", code="won", label="Thành công")
        response = self._patch({"status": "won"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Không được chuyển trực tiếp", response.json()["detail"])

    def test_tao_tay_chan_co_hoi_trung(self):
        response = self.client.post(
            reverse("rb-opportunities"),
            data=json.dumps({"person_id": self.an.pk, "product": PRODUCT_MORTGAGE}),
            content_type="application/json")
        self.assertEqual(response.status_code, 409)

    def test_tao_tay_chan_khach_da_yeu_cau_khong_lien_he(self):
        binh = Person.objects.create(display_name="Trần Bình")
        Relationship.objects.create(person=binh, domain="rb", do_not_contact=True)
        response = self.client.post(
            reverse("rb-opportunities"),
            data=json.dumps({"person_id": binh.pk, "product": PRODUCT_MORTGAGE}),
            content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertIn("không liên hệ", response.json()["detail"])
        self.assertFalse(RBOpportunity.objects.filter(person=binh).exists())

    def test_bo_loc_goc_nhin_khach_hang_loai_DNC_va_loc_theo_RM(self):
        from talent import search as talent_search
        binh = Person.objects.create(display_name="Trần Bình")
        Relationship.objects.create(person=binh, domain="rb", do_not_contact=True)
        RBProfile.objects.create(person=self.an, sales_owner=self.rm)
        _, rb_people = talent_search.search(domain="rb", limit=50)
        _, talent_people = talent_search.search(limit=50)
        self.assertNotIn(binh.pk, {p.pk for p in rb_people})
        self.assertIn(binh.pk, {p.pk for p in talent_people})
        _, owned = talent_search.search(domain="rb", owner=self.rm.pk, limit=50)
        self.assertEqual([p.pk for p in owned], [self.an.pk])

    def test_API_tim_goc_nhin_khach_hang_tra_tom_tat_ban_le(self):
        RBProfile.objects.create(person=self.an, sales_owner=self.rm,
                                 lead_status="warm", segment="priority")
        body = self.client.get(reverse("talent-search"),
                               {"domain": "rb", "segment": "priority"}).json()
        self.assertEqual([row["id"] for row in body["results"]], [self.an.pk])
        rb = body["results"][0]["rb"]
        self.assertEqual(rb["lead_status_label"], "Đã tiếp cận")
        self.assertEqual(rb["open_opportunity_products"], [PRODUCT_MORTGAGE])
        self.assertTrue(rb["sales_owner_name"])
        # Góc nhìn Tuyển dụng không kèm dữ liệu bán lẻ.
        talent_body = self.client.get(reverse("talent-search")).json()
        self.assertIsNone(talent_body["results"][0]["rb"])

    def test_API_tim_goc_nhin_khach_hang_chan_nguoi_khong_co_module_RB(self):
        self.client.force_login(make_user("tuyen-dung", roles.RECRUITER))
        response = self.client.get(reverse("talent-search"), {"domain": "rb"})
        self.assertEqual(response.status_code, 403)

    def test_goi_y_san_pham_qua_API(self):
        response = self.client.post(
            reverse("rb-suggest"),
            data=json.dumps({"text": "Sắp đi Nhật, nên đổi tiền hay dùng thẻ?"}),
            content_type="application/json")
        products = {row["product"] for row in response.json()["results"]}
        self.assertIn(PRODUCT_FX, products)

    def test_goi_y_tra_ve_ten_tieng_Viet(self):
        response = self.client.post(
            reverse("rb-suggest"), data=json.dumps({"text": "vay mua nhà"}),
            content_type="application/json")
        self.assertEqual(response.json()["results"][0]["product_label"], "Vay mua nhà")

    def test_san_khach_thay_ca_nguoi_chua_co_rb_profile(self):
        response = self.client.get(reverse("rb-customer-search"), {"q": "Nguyễn Văn An"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["person"], self.an.pk)

    def test_san_khach_loc_theo_trang_thai_va_lien_he(self):
        RBProfile.objects.create(person=self.an, lead_status=RBProfile.LEAD_WARM)
        response = self.client.get(reverse("rb-customer-search"),
                                   {"lead_status": "warm", "has_phone": "1"})
        self.assertEqual(response.json()["count"], 1)

    def test_rm_tao_nhom_khach_hang_tach_biet(self):
        response = self.client.post(reverse("talent-pools"),
                                    data=json.dumps({"name": "Khách ưu tiên", "domain": "rb"}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Pool.objects.get().domain, Pool.DOMAIN_RB)

    def test_canh_bao_rm_khac_dang_xu_ly(self):
        other = make_user("sales2", roles.RB_SALES)
        self.opportunity.assigned_to = self.rm
        self.opportunity.save()
        RBOpportunity.objects.create(person=self.an, product=PRODUCT_CREDIT_CARD,
                                     assigned_to=other)
        body = self.client.get(reverse("rb-opportunities")).json()
        first = next(row for row in body["results"] if row["id"] == self.opportunity.pk)
        self.assertIn("sales2", first["other_active_owners"])

    def test_lich_su_da_xem_rieng_cua_rm(self):
        RBProfile.objects.create(person=self.an)
        Interaction.objects.create(person=self.an, actor=self.rm, action="viewed", domain="rb")
        response = self.client.get(reverse("rb-recently-viewed"))
        self.assertEqual(response.json()["results"][0]["person"], self.an.pk)


class CustomerWorkInboxTest(TestCase):
    def setUp(self):
        self.rm = make_user("rm-inbox", roles.RB_SALES)
        self.other = make_user("rm-khac", roles.RB_SALES)
        self.client.force_login(self.rm)
        self.person = Person.objects.create(display_name="Khách nhiều nhu cầu")

    def _patch(self, opportunity, body):
        return self.client.patch(
            reverse("rb-opportunity", args=[opportunity.pk]),
            data=json.dumps(body), content_type="application/json")

    def test_inbox_gom_nhieu_co_hoi_va_lich_quan_he_thanh_mot_khach(self):
        first = RBOpportunity.objects.create(
            person=self.person, product=PRODUCT_MORTGAGE,
            assigned_to=self.rm, next_action_at=timezone.now() - timedelta(hours=1))
        RBOpportunity.objects.create(
            person=self.person, product=PRODUCT_CREDIT_CARD,
            assigned_to=self.rm, priority="low")
        Relationship.objects.create(
            person=self.person, domain="rb", owner_user=self.rm,
            next_action="Gọi xác nhận", next_action_at=timezone.now())

        response = self.client.get(reverse("rb-customer-tasks"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["opportunity"]["id"], first.pk)
        self.assertEqual(len(body["results"][0]["other_opportunities"]), 1)
        self.assertTrue(body["results"][0]["relationship_due"])

    def test_rm_khong_ghi_de_co_hoi_cua_rm_khac(self):
        opportunity = RBOpportunity.objects.create(
            person=self.person, product=PRODUCT_MORTGAGE, assigned_to=self.other)
        response = self._patch(opportunity, {"note": "Ghi đè"})
        self.assertEqual(response.status_code, 409)

    def test_nhan_viec_nguyen_tu_bao_xung_dot_khi_da_co_nguoi_nhan(self):
        opportunity = RBOpportunity.objects.create(
            person=self.person, product=PRODUCT_MORTGAGE, assigned_to=self.other)
        response = self._patch(opportunity, {"claim": True})
        self.assertEqual(response.status_code, 409)

    def test_luu_ghi_chu_khong_reset_moc_sla(self):
        entered = timezone.now() - timedelta(hours=8)
        opportunity = RBOpportunity.objects.create(
            person=self.person, product=PRODUCT_MORTGAGE,
            assigned_to=self.rm, stage_entered_at=entered)
        response = self._patch(opportunity, {"note": "Đã kiểm tra hồ sơ"})
        self.assertEqual(response.status_code, 200)
        opportunity.refresh_from_db()
        self.assertEqual(opportunity.stage_entered_at, entered)

    def test_trang_thai_ho_so_khong_bi_co_hoi_that_bai_ha_thap(self):
        won = RBOpportunity.objects.create(
            person=self.person, product=PRODUCT_MORTGAGE, assigned_to=self.rm)
        self._patch(won, {"status": "won"})
        lost = RBOpportunity.objects.create(
            person=self.person, product=PRODUCT_CREDIT_CARD, assigned_to=self.rm)
        self._patch(lost, {"status": "lost", "close_reason": "Không có nhu cầu"})
        self.assertEqual(RBProfile.objects.get(person=self.person).lead_status,
                         RBProfile.LEAD_CONVERTED)

    def test_bo_loc_va_phan_trang_sai_tra_400(self):
        self.assertEqual(self.client.get(
            reverse("rb-opportunities"), {"pool": "abc"}).status_code, 400)
        self.assertEqual(self.client.get(
            reverse("rb-customer-search"), {"limit": "abc"}).status_code, 400)
        self.assertEqual(self.client.get(
            reverse("rb-customer-tasks"), {"offset": "abc"}).status_code, 400)


class PermissionTest(TestCase):
    def test_recruiter_KHONG_doc_duoc_ho_so_ban_le(self):
        """RB Sales đọc được Talent (quyết định 19/08), chiều ngược lại chưa mở."""
        self.client.force_login(make_user("tuyendung", roles.RECRUITER))
        self.assertEqual(
            self.client.get(reverse("rb-opportunities")).status_code, 403)

    def test_quan_ly_doc_duoc(self):
        self.client.force_login(make_user("quanly", roles.MANAGER))
        self.assertEqual(
            self.client.get(reverse("rb-opportunities")).status_code, 200)

    def test_chua_dang_nhap_bi_chan(self):
        self.assertIn(self.client.get(reverse("rb-opportunities")).status_code,
                      (401, 403))


class OutreachTest(TestCase):
    """Soạn lời chào theo ngữ cảnh (mục 33) — bản song sinh của hiring/outreach.py."""

    def setUp(self):
        self.rm = make_user("sales", roles.RB_SALES)
        self.client.force_login(self.rm)
        self.person = Person.objects.create(display_name="Nguyễn Văn An",
                                            primary_phone="+84901234567")
        self.opportunity = RBOpportunity.objects.create(
            person=self.person, product=PRODUCT_MORTGAGE,
            need="Đang tính mua nhà", confidence=0.85,
            evidence={"excerpt": "Nhà em đang cần vay 500 triệu mua nhà"})

    def _post(self, name, args, body=None):
        return self.client.post(reverse(name, args=args),
                                data=json.dumps(body or {}),
                                content_type="application/json")

    def test_chi_dung_du_kien_CO_THAT(self):
        from . import outreach as outreach_module
        facts = outreach_module._facts(self.opportunity)
        self.assertTrue(any("mua nhà" in f for f in facts))

    def test_khong_co_du_kien_thi_khong_bia(self):
        from . import outreach as outreach_module
        trong = RBOpportunity.objects.create(
            person=Person.objects.create(display_name="Người lạ"),
            product=PRODUCT_SAVINGS)
        self.assertEqual(outreach_module._facts(trong), [])

    def test_soan_bang_LLM(self):
        from unittest import mock
        from ai.providers import Completion

        gia = Completion(
            text="Chào anh An, em bên MSB thấy anh đang tìm hiểu vay mua nhà, "
                 "anh có tiện trao đổi thêm không ạ?",
            provider="f", model="f", truncated=False)
        with mock.patch("rb.outreach.complete", return_value=gia):
            response = self._post("rb-outreach-draft", [self.opportunity.pk],
                                  {"channel": "message"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("mua nhà", response.json()["draft"])

    def test_khong_hua_lai_suat_hay_han_muc(self):
        """Không kiểm được nội dung LLM thật sinh ra, nhưng kiểm được là quy tắc
        đó nằm trong system prompt — chỗ duy nhất chặn được việc này."""
        from . import outreach as outreach_module
        self.assertIn("KHÔNG hứa lãi suất", outreach_module.SYSTEM_PROMPT)
        # Luật "không nói lộ nguồn" vẫn phải còn, chỉ là `28a0312` viết lại nó
        # thành câu cụ thể hơn. Neo vào Ý của luật, đừng neo vào một cách diễn
        # đạt — nếu không, mỗi lần trau prompt là test đỏ dù luật còn nguyên.
        self.assertIn("KHÔNG nhắc rằng thông tin đến từ", outreach_module.SYSTEM_PROMPT)

    def test_LLM_ban_thi_tra_KHUNG_de_ngo(self):
        from unittest import mock

        with mock.patch("rb.outreach.complete", side_effect=RuntimeError("bận")):
            response = self._post("rb-outreach-draft", [self.opportunity.pk], {})
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Nguyễn Văn An", body["draft"])
        self.assertIn("[Viết thêm", body["draft"])
        self.assertTrue(body["error"])

    def test_thu_cut_bi_loai(self):
        from unittest import mock
        from ai.providers import Completion

        gia = Completion(text="Chào anh", provider="f", model="f", truncated=True)
        with mock.patch("rb.outreach.complete", return_value=gia):
            response = self._post("rb-outreach-draft", [self.opportunity.pk], {})
        self.assertIn("[Viết thêm", response.json()["draft"])

    def test_kenh_la_thi_400(self):
        response = self._post("rb-outreach-draft", [self.opportunity.pk],
                              {"channel": "fax"})
        self.assertEqual(response.status_code, 400)

    def test_noi_dung_duoc_luu(self):
        from unittest import mock
        from ai.providers import Completion

        gia = Completion(text="Nội dung hợp lệ đủ dài để không bị coi là cụt.",
                         provider="f", model="f", truncated=False)
        with mock.patch("rb.outreach.complete", return_value=gia):
            self._post("rb-outreach-draft", [self.opportunity.pk], {})
        self.opportunity.refresh_from_db()
        self.assertTrue(self.opportunity.outreach_draft)
        self.assertEqual(self.opportunity.assigned_to, self.rm)

    def test_he_thong_KHONG_tu_gui(self):
        """Chỉ ghi nhận RM đã gửi — nhắn khách hàng thật cần người quyết."""
        response = self._post("rb-outreach-sent", [self.opportunity.pk],
                              {"channel": "message"})
        self.assertEqual(response.status_code, 200)
        self.opportunity.refresh_from_db()
        self.assertIsNotNone(self.opportunity.outreach_sent_at)
        self.assertEqual(self.opportunity.status, RBOpportunity.STATUS_CONTACTING)
        self.assertEqual(self.opportunity.assigned_to, self.rm)
        self.assertTrue(Interaction.objects.filter(
            person=self.person, action="rb_outreach_sent", domain="rb").exists())
        self.assertTrue(RBOpportunityStatusEvent.objects.filter(
            opportunity=self.opportunity, from_status="new",
            to_status="contacting").exists())

    def test_xac_nhan_gui_luu_dung_ban_rm_vua_sua_trong_mot_giao_dich(self):
        self.opportunity.outreach_draft = "Bản cũ"
        self.opportunity.save()
        response = self._post("rb-outreach-sent", [self.opportunity.pk],
                              {"channel": "message", "draft": "Bản cuối RM đã sửa"})
        self.assertEqual(response.status_code, 200)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.outreach_draft, "Bản cuối RM đã sửa")
        interaction = Interaction.objects.get(
            person=self.person, action="rb_outreach_sent", domain="rb")
        self.assertEqual(interaction.detail["text"], "Bản cuối RM đã sửa")

    def test_gui_dong_bo_ho_so_khach(self):
        self._post("rb-outreach-sent", [self.opportunity.pk], {})
        profile = RBProfile.objects.get(person=self.person)
        self.assertEqual(profile.lead_status, RBProfile.LEAD_INTERESTED)
        relation = Relationship.objects.get(person=self.person, domain="rb")
        self.assertEqual(relation.state, RBProfile.LEAD_INTERESTED)
        self.assertEqual(relation.owner_user, self.rm)
        self.assertIsNotNone(relation.last_contact_at)

    def test_khong_soan_hoac_ghi_nhan_gui_khi_khach_DNC(self):
        Relationship.objects.create(
            person=self.person, domain="rb", state="cold", do_not_contact=True)
        self.assertEqual(
            self._post("rb-outreach-draft", [self.opportunity.pk], {}).status_code, 409)
        self.assertEqual(
            self._post("rb-outreach-sent", [self.opportunity.pk], {}).status_code, 409)

    def test_luu_nhap_qua_PATCH(self):
        response = self.client.patch(
            reverse("rb-opportunity", args=[self.opportunity.pk]),
            data=json.dumps({"outreach_draft": "Bản nháp RM tự sửa"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.opportunity.refresh_from_db()
        self.assertEqual(self.opportunity.outreach_draft, "Bản nháp RM tự sửa")


class AgentTest(TestCase):
    """RB Radar Agent — gộp ý định + khớp người + gợi ý sản phẩm vào một lượt."""

    def setUp(self):
        self.rm = make_user("sales", roles.RB_SALES)
        self.client.force_login(self.rm)
        self.an = Person.objects.create(display_name="Nguyễn Văn An",
                                        primary_phone="+84901234567")
        # Khớp người đi qua bảng Identity, không đọc thẳng `primary_phone` —
        # phải có định danh mạnh thì mới khớp được, giống hệt dữ liệu thật.
        self.an.identities.create(kind="phone", value="+84901234567")

    def _post(self, body):
        return self.client.post(reverse("rb-agent-analyze"),
                                data=json.dumps(body), content_type="application/json")

    def _detect(self, scores, contacts=None):
        class Gia:
            def score(self, domain):
                return scores.get(domain, 0.0)
            reason = "vì lý do trong bài"
            contacts = {}
            def as_dict(self):
                return {"scores": scores, "reason": self.reason,
                        "contacts": self.contacts}
        gia = Gia()
        gia.contacts = contacts or {}
        return mock.patch("social.intent.detect", return_value=gia)

    def test_gop_y_dinh_va_goi_y_san_pham_TRONG_MOT_luot(self):
        with self._detect({"rb": 0.85}, contacts={"phone": "0901234567"}):
            body = self._post({"text": "Em cần vay mua nhà, LH 0901234567"}).json()
        self.assertGreater(len(body["products"]), 0)
        self.assertEqual(body["matched_person_name"], "Nguyễn Văn An")

    def test_khong_lam_gi_khong_luu_gi(self):
        """Đây là công cụ xem trước — giống hệt social.analyze mặc định."""
        with self._detect({"rb": 0.85}, contacts={"phone": "0901234567"}):
            self._post({"text": "Em cần vay mua nhà, LH 0901234567"})
        self.assertEqual(RBOpportunity.objects.count(), 0)
        self.assertEqual(ProductInterest.objects.count(), 0)

    def test_bao_da_co_co_hoi_dang_mo_de_khong_tao_trung(self):
        RBOpportunity.objects.create(person=self.an, product=PRODUCT_MORTGAGE,
                                     status=RBOpportunity.STATUS_NEW)
        with self._detect({"rb": 0.85}, contacts={"phone": "0901234567"}):
            body = self._post({"text": "Em cần vay mua nhà, LH 0901234567"}).json()
        self.assertEqual(len(body["existing_opportunities"]), 1)
        self.assertTrue(any("đừng tạo trùng" in a for a in body["suggested_actions"]))

    def test_khong_khop_nguoi_thi_noi_ro_trong_hanh_dong_de_xuat(self):
        with self._detect({"rb": 0.85}):
            body = self._post({"text": "Em cần vay mua nhà"}).json()
        self.assertIsNone(body["matched_person"])
        self.assertTrue(any("Chưa khớp" in a for a in body["suggested_actions"]))

    def test_diem_thap_thi_khong_goi_y_san_pham(self):
        with self._detect({"rb": 0.1}):
            body = self._post({"text": "Hôm nay trời đẹp"}).json()
        self.assertEqual(body["products"], [])

    def test_co_luu_lai_AgentRun(self):
        from agents.models import AgentRun

        with self._detect({"rb": 0.85}, contacts={"phone": "0901234567"}):
            self._post({"text": "Em cần vay mua nhà, LH 0901234567"})
        run = AgentRun.objects.get()
        self.assertEqual(run.agent, "rb")
        self.assertEqual(run.status, AgentRun.STATUS_OK)
        self.assertGreater(run.steps.count(), 0)

    def test_van_ban_trong_thi_400(self):
        self.assertEqual(self._post({"text": " "}).status_code, 400)


class MetricsTest(TestCase):
    """Chỉ số mục 50 cho RB Radar — cùng nguyên tắc với hiring/metrics.py."""

    def setUp(self):
        self.hm = make_user("sales", roles.RB_SALES)
        self.client.force_login(self.hm)

    def test_chua_co_du_lieu_thi_tra_None_KHONG_tra_0(self):
        from . import metrics
        rows = metrics.collect()
        for row in rows.values():
            self.assertIsNone(row["value"])
        self.assertIn("Chưa", rows["win_rate"]["detail"])

    def test_chot_thanh_cong_chi_tinh_co_hoi_DA_DONG(self):
        from . import metrics
        for status_value in ("new", "won", "lost", "won"):
            RBOpportunity.objects.create(
                person=Person.objects.create(display_name=f"N{status_value}{RBOpportunity.objects.count()}"),
                product=PRODUCT_MORTGAGE, status=status_value)
        row = metrics.collect()["win_rate"]
        # 3 da dong (2 won, 1 lost) -> ti le 2/3, khong tinh ca "new".
        self.assertAlmostEqual(row["value"], 2 / 3, places=3)
        self.assertIn("2/3", row["detail"])

    def test_tu_tin_hieu_dem_dung_co_hoi_co_signal(self):
        from . import metrics
        a = Person.objects.create(display_name="A")
        b = Person.objects.create(display_name="B")
        signal = Signal.objects.create(
            person=a, domain="rb", signal_type="financial_need", confidence=0.9,
            observed_at=timezone.now())
        RBOpportunity.objects.create(person=a, product=PRODUCT_MORTGAGE, signal=signal)
        RBOpportunity.objects.create(person=b, product=PRODUCT_SAVINGS)  # RM tự tạo

        row = metrics.collect()["from_signal"]
        self.assertEqual(row["value"], 0.5)
        self.assertIn("1/2", row["detail"])

    def test_thoi_gian_toi_lien_he_dung_TRUNG_VI(self):
        from . import metrics
        now = timezone.now()
        for phut in (10, 20, 60 * 24 * 20):
            opp = RBOpportunity.objects.create(
                person=Person.objects.create(display_name=f"N{phut}"),
                product=PRODUCT_MORTGAGE)
            opp.outreach_sent_at = now + timezone.timedelta(minutes=phut)
            opp.save()
            RBOpportunity.objects.filter(pk=opp.pk).update(
                created_at=now, outreach_sent_at=now + timezone.timedelta(minutes=phut))

        row = metrics.collect()["time_to_contact"]
        self.assertEqual(row["value"], 20)
        self.assertEqual(row["unit"], "phút")

    def test_co_hoi_co_ket_qua_khac_chot_thanh_cong(self):
        """resolution_rate đo có ĐÓNG hay không; win_rate đo chất lượng trong
        số đã đóng — hai câu hỏi khác nhau, không được trộn."""
        from . import metrics
        for status_value in ("new", "accepted", "won"):
            RBOpportunity.objects.create(
                person=Person.objects.create(display_name=f"N{status_value}"),
                product=PRODUCT_MORTGAGE, status=status_value)
        rows = metrics.collect()
        self.assertAlmostEqual(rows["resolution_rate"]["value"], 1 / 3, places=3)
        self.assertEqual(rows["win_rate"]["value"], 1.0)

    def test_du_lieu_di_qua_API(self):
        response = self.client.get(reverse("rb-metrics"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("win_rate", response.json()["metrics"])


class OpportunityExportTest(TestCase):
    """Xuất CSV hộp thư cơ hội (Master Plan mục 15)."""

    def setUp(self):
        self.rm = make_user("sales2", roles.RB_SALES)
        self.client.force_login(self.rm)
        a = Person.objects.create(display_name="Nguyễn Văn An",
                                  primary_phone="+84901234567")
        RBOpportunity.objects.create(person=a, product=PRODUCT_MORTGAGE,
                                     need="Đang tính mua nhà", confidence=0.85,
                                     status=RBOpportunity.STATUS_NEW)

    def test_xuat_ra_dung_CSV(self):
        response = self.client.get(reverse("rb-opportunities-export"))
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8-sig")
        self.assertIn("Nguyễn Văn An", text)
        self.assertIn("Vay mua nhà", text)

    def test_loc_theo_trang_thai_mo(self):
        won = Person.objects.create(display_name="Đã chốt")
        RBOpportunity.objects.create(person=won, product=PRODUCT_MORTGAGE,
                                     status=RBOpportunity.STATUS_WON)
        response = self.client.get(reverse("rb-opportunities-export"), {"open": "1"})
        text = response.content.decode("utf-8-sig")
        self.assertIn("Nguyễn Văn An", text)
        self.assertNotIn("Đã chốt", text)

    def test_chua_dang_nhap_bi_chan(self):
        self.client.logout()
        self.assertIn(
            self.client.get(reverse("rb-opportunities-export")).status_code, (401, 403))
