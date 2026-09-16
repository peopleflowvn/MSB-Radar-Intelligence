# -*- coding: utf-8 -*-
"""Tìm prospect bằng ngôn ngữ tự nhiên (Master Plan mục 16, Task 6).

Ba điều bài này canh kỹ nhất:

1. **Tiêu chí luôn hiện ra.** Không có tiêu chí thì RM không biết hệ thống hiểu
   câu hỏi thế nào, và không sửa được khi hiểu sai — đó là hộp đen.
2. **Mất AI không làm hỏng ô tìm kiếm.** Ba đường bóc tách, đường nào hỏng thì
   rơi xuống đường dưới, và luôn còn nhánh tất định ở đáy.
3. **DNC không bao giờ lọt vào kết quả**, kể cả khi RM hỏi đúng nhóm đó.
"""
from unittest import mock

from accounts import roles
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from people.models import Person, Signal

from . import prospects, routing
from .models import (PRODUCT_CREDIT_CARD, PRODUCT_MORTGAGE, RBOpportunity,
                     RBProfile)


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class ParseTest(TestCase):
    """Bóc tách câu hỏi. Ba đường, luôn có đáy tất định."""

    def test_cau_hoi_rong_khong_no(self):
        parsed = prospects.parse("")
        self.assertEqual(parsed.criteria["limit"], prospects.DEFAULT_LIMIT)

    def test_do_tu_khoa_khi_LLM_hong(self):
        def sap(*_args, **_kwargs):
            raise RuntimeError("nhà cung cấp sập")

        with mock.patch("rb.prospects.AGENT_ENDPOINT", ""):
            parsed = prospects.parse(
                "Tìm 15 quản lý ở Hà Nội có contact, quan tâm Thẻ tín dụng",
                complete_fn=sap)
            self.assertEqual(parsed.source, "keyword")
            self.assertEqual(parsed.criteria["seniority"], "manager")
            self.assertEqual(parsed.criteria["limit"], 15)
            self.assertTrue(parsed.criteria["require_contact"])
            self.assertIn(PRODUCT_CREDIT_CARD, parsed.criteria["products"])
            self.assertTrue(parsed.error)

    def test_LLM_KHONG_duoc_bia_gia_tri(self):
        """Chốt chặn cuối: giá trị lạ không được đi tiếp vào truy vấn."""
        result = mock.Mock(text='{"products": ["crypto"], "seniority": "vua",'
                                ' "segment": "sieu-vip", "limit": 99999}',
                          provider="greennode", model="z-ai/glm-5.2-hackathon")
        parsed = prospects.parse("tìm khách", complete_fn=lambda *a, **k: result)
        self.assertEqual(parsed.criteria["products"], [])
        self.assertEqual(parsed.criteria["seniority"], "")
        self.assertEqual(parsed.criteria["segment"], "")
        self.assertEqual(parsed.criteria["limit"], prospects.DEFAULT_LIMIT)

    def test_hoi_tiep_giu_lai_tieu_chi_truoc_do(self):
        """Hỏi tiếp chỉ nói THAY ĐỔI gì — tiêu chí trước không được biến mất."""
        # Mô hình chỉ trả về location mới, không nhắc lại products/limit của lượt trước.
        result = mock.Mock(text='{"location": "Đà Nẵng"}', provider="greennode",
                          model="z-ai/glm-5.2-hackathon")
        history = [{"criteria": {**prospects._empty(), "products": ["credit_card"],
                                 "limit": 15, "location": "Hà Nội",
                                 "require_contact": True}}]
        parsed = prospects.parse("vậy còn ở Đà Nẵng thì sao",
                                 complete_fn=lambda *a, **k: result, history=history)
        self.assertEqual(parsed.criteria["location"], "Đà Nẵng")
        self.assertEqual(parsed.criteria["products"], ["credit_card"])
        self.assertEqual(parsed.criteria["limit"], 15)
        self.assertTrue(parsed.criteria["require_contact"])

    def test_khong_co_history_thi_hoi_doc_lap_nhu_truoc(self):
        result = mock.Mock(text='{"location": "Đà Nẵng"}', provider="greennode",
                          model="z-ai/glm-5.2-hackathon")
        parsed = prospects.parse("tìm khách ở Đà Nẵng", complete_fn=lambda *a, **k: result)
        self.assertEqual(parsed.criteria["products"], [])

    def test_dia_danh_duoc_chuan_hoa_luc_boc_tach(self):
        """RM thấy đúng dạng chuẩn ngay trên tiêu chí, không phải đợi tới lúc lọc."""
        result = mock.Mock(text='{"location": "Sài Gòn"}', provider="greennode",
                          model="z-ai/glm-5.2-hackathon")
        parsed = prospects.parse("tìm khách ở sài gòn", complete_fn=lambda *a, **k: result)
        self.assertEqual(parsed.criteria["location"], "Hồ Chí Minh")

    def test_gioi_han_khong_vuot_tran(self):
        result = mock.Mock(text='{"limit": 500}', provider="greennode", model="z-ai/glm-5.2-hackathon")
        parsed = prospects.parse("tìm khách", complete_fn=lambda *a, **k: result)
        self.assertLessEqual(parsed.criteria["limit"], prospects.MAX_LIMIT)

    def test_LLM_tra_ve_rac_thi_lui_ve_do_tu_khoa(self):
        result = mock.Mock(text="xin chào")
        parsed = prospects.parse("quản lý ở Hà Nội",
                                 complete_fn=lambda *a, **k: result)
        self.assertEqual(parsed.criteria["seniority"], "manager")

    def test_uy_quyen_cho_agent_khi_da_cau_hinh(self):
        """Agent trên AgentBase bóc tách thì Hub ghi nhận đúng nguồn."""
        with mock.patch.object(prospects, "AGENT_ENDPOINT", "https://agent.test"), \
             mock.patch.object(prospects, "_ask_agent",
                               return_value=({"seniority": "executive",
                                              "location": "Đà Nẵng"},
                                             "z-ai/glm-5.2-hackathon", "")):
            parsed = prospects.parse("tìm giám đốc")
        self.assertEqual(parsed.source, "agent")
        self.assertEqual(parsed.criteria["seniority"], "executive")
        self.assertEqual(parsed.model, "z-ai/glm-5.2-hackathon")
        self.assertEqual(parsed.provider, "greennode")

    def test_agent_hong_thi_lui_ve_LLM_tai_Hub(self):
        """Sản phẩm không được phụ thuộc cứng vào một endpoint bên ngoài."""
        result = mock.Mock(text='{"seniority": "manager"}', provider="greennode",
                          model="z-ai/glm-5.2-hackathon")
        with mock.patch.object(prospects, "AGENT_ENDPOINT", "https://agent.test"), \
             mock.patch.object(prospects, "_ask_agent",
                               return_value=(None, "", "hết thời gian chờ")):
            parsed = prospects.parse("tìm quản lý",
                                     complete_fn=lambda *a, **k: result)
        self.assertEqual(parsed.source, "llm")
        self.assertEqual(parsed.criteria["seniority"], "manager")

    def test_agent_tra_ve_khuon_la_van_bi_loc(self):
        """Hub không tin một dịch vụ bên ngoài chỉ vì nó là dịch vụ của mình."""
        with mock.patch.object(prospects, "AGENT_ENDPOINT", "https://agent.test"), \
             mock.patch.object(prospects, "_ask_agent",
                               return_value=({"products": ["khong-co-that"]}, "z-ai/glm-5.2-hackathon", "")):
            parsed = prospects.parse("tìm khách")
        self.assertEqual(parsed.criteria["products"], [])


class SearchTest(TestCase):
    def setUp(self):
        self.an = Person.objects.create(display_name="Nguyễn Văn An",
                                        location="Hà Nội",
                                        primary_phone="+84901234567")
        RBProfile.objects.create(person=self.an, occupation="Trưởng phòng kinh doanh")
        self.binh = Person.objects.create(display_name="Trần Bình",
                                          location="Đà Nẵng")
        RBProfile.objects.create(person=self.binh, occupation="Nhân viên")

    def _criteria(self, **kwargs):
        return dict(prospects._empty(), **kwargs)

    def test_loc_theo_dia_diem(self):
        rows = prospects.search(self._criteria(location="Hà Nội"))
        self.assertEqual([row["person_id"] for row in rows], [self.an.pk])

    def test_loc_khac_cach_viet_van_khop_dung_nguoi(self):
        """"Sài Gòn" và "Hồ Chí Minh" là cùng một nơi — xem core/vn_locations.py."""
        chi = Person.objects.create(display_name="Lê Thị Chi", location="Hồ Chí Minh")
        RBProfile.objects.create(person=chi, occupation="Chủ shop online")
        rows = prospects.search(self._criteria(location="Sài Gòn"))
        self.assertEqual([row["person_id"] for row in rows], [chi.pk])

    def test_loc_theo_cap_bac(self):
        rows = prospects.search(self._criteria(seniority="manager"))
        self.assertEqual([row["person_id"] for row in rows], [self.an.pk])

    def test_yeu_cau_co_lien_he(self):
        rows = prospects.search(self._criteria(require_contact=True))
        self.assertEqual([row["person_id"] for row in rows], [self.an.pk])

    def test_DNC_KHONG_BAO_GIO_lot_vao_ket_qua(self):
        """Ràng buộc tuân thủ, không phải bộ lọc — kể cả khi RM hỏi đúng nhóm đó."""
        from people.models import Relationship

        Relationship.objects.create(person=self.an, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        rows = prospects.search(self._criteria(location="Hà Nội"))
        self.assertEqual(rows, [])

    def test_loai_nguoi_da_co_co_hoi_dang_mo(self):
        RBOpportunity.objects.create(person=self.an, product=PRODUCT_MORTGAGE,
                                     status=RBOpportunity.STATUS_ACCEPTED)
        rows = prospects.search(self._criteria(exclude_open_opportunity=True))
        self.assertNotIn(self.an.pk, [row["person_id"] for row in rows])

    def test_moi_ket_qua_deu_co_diem_va_ly_do(self):
        rows = prospects.search(self._criteria(location="Hà Nội"))
        row = rows[0]
        self.assertGreater(row["priority_score"], 0)
        self.assertTrue(row["why"])
        for chieu in ("fit", "need", "timing", "reachability", "value"):
            self.assertIn(chieu, row["scores"])

    def test_xep_theo_diem_chu_khong_theo_ngay_sua(self):
        """Cắt trước khi chấm sẽ trả nhóm sửa gần đây nhất, không phải nhóm hợp nhất."""
        rows = prospects.search(self._criteria(limit=10))
        diem = [row["priority_score"] for row in rows]
        self.assertEqual(diem, sorted(diem, reverse=True))

    def test_khach_hop_nhat_khong_bi_cat_vi_ho_so_lau_khong_sua(self):
        """Tái hiện đúng lỗi cũ, thay vì chỉ kiểm tra danh sách trả về đã sắp.

        Bản cũ lấy `order_by("-updated_at")[:limit * 3]`, nên chỉ cần nhiều hơn
        `limit * 3` người thoả bộ lọc là người điểm cao nhất bị cắt TRƯỚC khi
        `_score` chạy — miễn hồ sơ của họ lâu nhất không ai sửa. Danh sách trả
        về vẫn sắp giảm dần nên test cũ vẫn xanh: nó canh chặng sắp xếp, còn
        lỗi nằm ở chặng cắt.
        """
        from django.utils import timezone

        limit = 2
        # Người điểm cao nhất: có liên hệ + đúng cấp bậc, và được tạo TRƯỚC TIÊN
        # nên `updated_at` cũ nhất — đúng nhóm mà bản cũ cắt mất.
        tot_nhat = Person.objects.create(
            display_name="Phạm Tốt Nhất", location="Hải Phòng",
            primary_phone="+84908888888", primary_email="tot@example.test")
        RBProfile.objects.create(person=tot_nhat, occupation="Giám đốc điều hành",
                                 segment=RBProfile.SEGMENT_PRIORITY)
        for index in range(limit * 3 + 2):
            nguoi = Person.objects.create(display_name="Khách nền %d" % index,
                                          location="Hải Phòng")
            RBProfile.objects.create(person=nguoi, occupation="Nhân viên")

        # `updated_at` là auto_now — ép lại bằng update() để không chạm save().
        Person.objects.filter(pk=tot_nhat.pk).update(
            updated_at=timezone.now() - timezone.timedelta(days=900))

        rows = prospects.search(self._criteria(location="Hải Phòng", limit=limit))
        self.assertIn(tot_nhat.pk, [row["person_id"] for row in rows])

    def test_coverage_noi_ro_khi_danh_sach_bi_cat(self):
        """Nhóm lọc vượt ngân sách chấm điểm phải NÓI RA, không im lặng."""
        rows = prospects.search(self._criteria(location="Hà Nội"))
        self.assertFalse(rows.truncated)
        self.assertEqual(rows.coverage, {"scanned": rows.scanned, "truncated": False})

        with mock.patch.object(prospects, "SCORING_BUDGET", 1):
            chat = prospects.search(self._criteria(location="Hà Nội", limit=10))
        self.assertEqual(chat.scanned, 1)

    def test_thu_tu_on_dinh_khi_diem_bang_nhau(self):
        """Điểm bằng nhau không được cho ra hai thứ tự khác nhau giữa hai lần chạy."""
        for index in range(6):
            nguoi = Person.objects.create(display_name="Khách đều %d" % index,
                                          location="Cần Thơ")
            RBProfile.objects.create(person=nguoi, occupation="Nhân viên")
        lan_dau = [row["person_id"] for row in
                   prospects.search(self._criteria(location="Cần Thơ", limit=4))]
        lan_sau = [row["person_id"] for row in
                   prospects.search(self._criteria(location="Cần Thơ", limit=4))]
        self.assertEqual(lan_dau, lan_sau)
        self.assertEqual(lan_dau, sorted(lan_dau))

    def test_ton_trong_gioi_han_so_luong(self):
        for index in range(5):
            person = Person.objects.create(display_name="Khách %d" % index,
                                           location="Hà Nội",
                                           primary_phone="+84900000%03d" % index)
            RBProfile.objects.create(person=person, occupation="Quản lý")
        rows = prospects.search(self._criteria(location="Hà Nội", limit=3))
        self.assertEqual(len(rows), 3)

    def test_dung_LAI_cong_thuc_cham_diem_cua_rb_scoring(self):
        """Không có công thức thứ hai — lệch nhau thì không ai giải thích được."""
        from . import scoring

        row = prospects.search(self._criteria(location="Hà Nội"))[0]
        expected = scoring.priority_score(
            row["scores"]["fit"], row["scores"]["need"], row["scores"]["timing"],
            row["scores"]["reachability"], row["scores"]["value"],
            strategic_weight=scoring.score_value(row["product"])[2])
        self.assertAlmostEqual(row["priority_score"], expected, places=1)


class ProspectApiTest(TestCase):
    def setUp(self):
        self.rm = make_user("rm-prospect", roles.RB_SALES)
        self.client.force_login(self.rm)
        self.an = Person.objects.create(display_name="Nguyễn Văn An",
                                        location="Hà Nội",
                                        primary_phone="+84901234567")
        profile = RBProfile.objects.create(person=self.an,
                                           occupation="Trưởng phòng kinh doanh")
        routing.record_interests(
            self.an,
            routing.suggest_products("Em muốn mở thẻ tín dụng", base_confidence=0.9),
            source="social", observed_at=timezone.now())
        self.assertTrue(profile.interests.exists())

    def _ask(self, question):
        def sap(*_args, **_kwargs):
            raise RuntimeError("không gọi LLM trong test")

        with mock.patch.object(prospects, "complete", sap):
            return self.client.post(reverse("rb-prospects"), {"q": question},
                                    content_type="application/json")

    def test_tra_ve_ca_tieu_chi_lan_ket_qua(self):
        """Thiếu tiêu chí thì RM không sửa được khi hệ thống hiểu sai."""
        body = self._ask("Tìm 10 quản lý ở Hà Nội có contact").json()
        self.assertIn("criteria", body)
        self.assertIn("criteria_from", body)
        self.assertEqual(body["criteria"]["seniority"], "manager")
        self.assertEqual(body["count"], len(body["results"]))

    def test_cau_hoi_rong_bi_tu_choi(self):
        response = self.client.post(reverse("rb-prospects"), {"q": "  "},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_cau_hoi_ai_tao_ra_ban_duoc_tra_loi_dung_trong_tam(self):
        with mock.patch.object(prospects, "run") as search:
            response = self.client.post(reverse("rb-prospects"),
                                        {"q": "Ai tạo ra bạn?"},
                                        content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "conversation")
        self.assertIn("MSB Radar", response.json()["answer"])
        search.assert_not_called()

    def test_cau_hoi_qua_dai_bi_tu_choi(self):
        response = self.client.post(reverse("rb-prospects"), {"q": "x" * 1200},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_KHONG_lo_lien_he_day_du(self):
        """Màn hình mới nhất cũng phải theo luật che PII, không được miễn trừ."""
        payload = self._ask("Tìm khách ở Hà Nội").content.decode("utf-8")
        self.assertNotIn("+84901234567", payload)

    def test_chua_dang_nhap_bi_chan(self):
        self.client.logout()
        response = self.client.post(reverse("rb-prospects"), {"q": "tìm khách"},
                                    content_type="application/json")
        self.assertIn(response.status_code, (401, 403))

    def test_vai_tro_khong_phai_RB_bi_chan(self):
        self.client.force_login(make_user("edge-prospect", roles.EDGE_OPERATOR))
        response = self.client.post(reverse("rb-prospects"), {"q": "tìm khách"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)
