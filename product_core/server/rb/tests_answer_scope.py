# -*- coding: utf-8 -*-
"""Growth: câu đếm, câu tổng hợp toàn kho, và điều RM đã dặn.

Thứ bị ghim ở đây là SỰ TRUNG THỰC của con số: một con số dán nhãn chính xác
phải thật sự là số đếm toàn phạm vi; con số từ phần đã đọc phải nói rõ là ước
lượng và nói đã đọc bao nhiêu trên bao nhiêu.
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from people.models import Person, Relationship, Signal

from .answer import count as count_stage
from .answer import engine
from .answer import retrieve as retrieve_stage
from .answer.corpus import overview
from .answer.plan import ProspectPlan
from .answer.structured import analyse_phrase, analyse_plan
from .models import ProductInterest, RBProfile


class FakeCompletion:
    def __init__(self, text):
        self.text, self.provider, self.model, self.truncated = text, "fake", "fake-1", False


def plan_json(**payload):
    payload.setdefault("suy_luan", "test")
    payload.setdefault("do_tin_cay", 0.95)

    def caller(messages, **kwargs):
        return FakeCompletion(json.dumps(payload, ensure_ascii=False))
    return caller


def _customer(name, *, location="", phone="", owner=None, products=()):
    person = Person.objects.create(display_name=name, location=location,
                                   primary_phone=phone, is_applicant=False)
    profile = RBProfile.objects.create(person=person, sales_owner=owner)
    for product in products:
        ProductInterest.objects.create(profile=profile, product=product, confidence=0.8,
                                       observed_at=timezone.now())
    return person


class StructuredConditionTest(SimpleTestCase):
    """Sai theo chiều "chính xác" là con số sai mang nhãn đúng — nên phải bảo thủ."""

    def test_dieu_kien_co_cau_truc(self):
        for phrase in ("ở Hà Nội", "quan tâm vay mua nhà", "có số điện thoại",
                       "chưa có cơ hội đang mở", "phân khúc ưu tiên", "đang ở Sài Gòn",
                       "có tín hiệu trong 30 ngày"):
            with self.subTest(phrase=phrase):
                self.assertTrue(analyse_phrase(phrase).covered)

    def test_con_chu_khong_nhan_ra_thi_khong_co_cau_truc(self):
        for phrase in ("mới kết hôn", "quan tâm vay mua nhà vì mới kết hôn", "khách cần vay"):
            with self.subTest(phrase=phrase):
                self.assertFalse(analyse_phrase(phrase).covered)

    def test_phu_dinh_khong_bao_gio_co_cau_truc(self):
        """Khớp đúng từ khoá sản phẩm; đếm nó như có quan tâm là đếm ngược nghĩa."""
        self.assertFalse(analyse_phrase("không quan tâm vay mua nhà").covered)

    def test_hai_cum_san_pham_la_AND_mot_cum_hoac_la_OR(self):
        result = analyse_plan(ProspectPlan(must_have=["quan tâm vay mua nhà",
                                                      "quan tâm thẻ tín dụng"]))
        self.assertEqual(result.product_groups, [["mortgage"], ["credit_card"]])
        one = analyse_plan(ProspectPlan(must_have=["mua nhà hoặc mua xe"]))
        self.assertEqual(one.product_groups, [["mortgage", "auto_loan"]])

    def test_mau_thuan_tren_mot_cot_thi_khong_doan(self):
        result = analyse_plan(ProspectPlan(must_have=["ở Hà Nội", "ở Đà Nẵng"]))
        self.assertFalse(result.all_covered)


class ExactCountTest(TestCase):
    def setUp(self):
        self.hn_nha = _customer("HN Nhà", location="Hà Nội", products=["mortgage"])
        self.hn_nha_the = _customer("HN Nhà Thẻ", location="Hà Nội",
                                    products=["mortgage", "credit_card"])
        self.dn_nha = _customer("ĐN Nhà", location="Đà Nẵng", products=["mortgage"])
        self.hn_khong = _customer("HN Không Quan Tâm", location="Hà Nội")
        Person.objects.create(display_name="Ứng Viên HN", location="Hà Nội")  # không phải khách

    def _count(self, must_have, shape="count", user=None):
        plan = ProspectPlan(shape=shape, must_have=must_have)
        analysis = analyse_plan(plan)
        self.assertTrue(analysis.all_covered)
        return count_stage.exact(plan, analysis, user=user)

    def test_dem_chinh_xac_toan_kho_khong_tinh_ung_vien(self):
        out = self._count(["ở Hà Nội", "quan tâm vay mua nhà"])
        self.assertEqual(out["matched"], 2)
        self.assertEqual(out["scope_total"], 4)          # ứng viên HN không vào mẫu số

    def test_hai_nhom_san_pham_la_AND(self):
        self.assertEqual(self._count(["quan tâm vay mua nhà", "quan tâm thẻ tín dụng"])["matched"], 1)

    def test_khach_khong_lien_he_khong_duoc_dem(self):
        Relationship.objects.create(person=self.hn_nha, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        self.assertEqual(self._count(["ở Hà Nội", "quan tâm vay mua nhà"])["matched"], 1)

    def test_khong_dieu_kien_la_dem_ca_pham_vi(self):
        self.assertEqual(self._count([])["matched"], 4)

    def test_portfolio_chi_dem_khach_cua_rm(self):
        rm = get_user_model().objects.create_user("count-rm")
        _customer("Của RM", location="Hà Nội", owner=rm, products=["mortgage"])
        out = count_stage.exact(ProspectPlan(shape="portfolio", must_have=["quan tâm vay mua nhà"]),
                                analyse_plan(ProspectPlan(must_have=["quan tâm vay mua nhà"])),
                                user=rm)
        self.assertEqual((out["matched"], out["scope_total"]), (1, 1))


class CountEngineTest(TestCase):
    def setUp(self):
        _customer("A", location="Hà Nội", products=["mortgage"])
        _customer("B", location="Hà Nội", products=["mortgage"])
        _customer("C", location="Đà Nẵng", products=["mortgage"])

    def test_dieu_kien_co_cau_truc_thi_SQL_khong_doc_bang_chung(self):
        with mock.patch.object(retrieve_stage, "retrieve") as retrieve:
            result = engine.answer("bao nhiêu khách ở Hà Nội quan tâm vay mua nhà",
                                   complete_fn=plan_json(shape="count",
                                                         must_have=["ở Hà Nội", "quan tâm vay mua nhà"]))
        retrieve.assert_not_called()
        self.assertTrue(result.trace["count"]["exact"])
        self.assertIn("**2**", result.text)
        self.assertIn("Trên tổng 3 khách", result.text)

    def test_can_doc_noi_dung_thi_noi_ro_la_uoc_luong(self):
        def caller(messages, **kwargs):
            body = messages[-1]["content"]
            if "DANH SÁCH KHÁCH HÀNG" in body:
                import re
                # Model giả đọc đủ mọi khách được gửi và kết luận không ai thoả.
                # (Trả `ket_qua` rỗng thì đúng ra là "không đọc được" — xem judge.)
                ids = [int(x) for x in re.findall(r"id=(\d+)", body)]
                return FakeCompletion(json.dumps({"ket_qua": [
                    {"id": pid, "thoa": False, "do_tin": 0.1} for pid in ids]}))
            return FakeCompletion(json.dumps({
                "suy_luan": "t", "shape": "count", "do_tin_cay": 0.95,
                "must_have": ["ở Hà Nội", "mới kết hôn"], "search_queries": ["kết hôn"]},
                ensure_ascii=False))
        result = engine.answer("bao nhiêu khách ở Hà Nội mới kết hôn", complete_fn=caller)
        count = result.trace["count"]
        self.assertFalse(count["exact"])
        self.assertEqual(count["population_after_structured_filters"], 2)
        self.assertIn("Không đếm chính xác", result.text)
        self.assertIn("ước lượng", result.text)
        self.assertNotIn("Đếm chính xác", result.text)


class AggregateUsesWholeStoreFactsTest(TestCase):
    """"Kho có bao nhiêu khách" không được trả lời bằng vài chục người vừa đọc."""

    def test_so_lieu_toan_kho_khong_tinh_ung_vien(self):
        _customer("Có SĐT", phone="0900000001", products=["mortgage"])
        _customer("Không SĐT")
        Person.objects.create(display_name="Ứng Viên")
        data = overview()
        self.assertEqual(data["tong_khach_hang"], 2)
        self.assertEqual(data["co_lien_he"], 1)
        self.assertEqual(data["quan_tam_san_pham"][0]["so_khach"], 1)

    def test_cau_tong_hop_gui_so_lieu_cho_model_ke_ca_khi_danh_sach_rong(self):
        _customer("Một Khách")
        seen = {}

        def streamer(messages, **kwargs):
            seen["messages"] = messages
            yield {"type": "answer", "text": "Kho có 1 khách."}
            yield {"type": "done", "completion": FakeCompletion("Kho có 1 khách.")}

        with mock.patch.object(retrieve_stage, "retrieve", return_value=[]):
            result = engine.answer("tổng quan kho khách hàng",
                                   complete_fn=plan_json(shape="analyze"), stream_fn=streamer)
        blob = "\n".join(m["content"] for m in seen["messages"])
        self.assertIn("SỐ LIỆU", blob)
        self.assertIn('"tong_khach_hang": 1', blob)
        self.assertEqual(result.text, "Kho có 1 khách.")


class MemoriesReachComposeTest(SimpleTestCase):
    def test_dieu_rm_da_dan_vao_prompt(self):
        from .answer import compose
        messages = compose.build_messages(ProspectPlan(), [], [], {}, [],
                                          memories=["tôi chỉ phụ trách quận Cầu Giấy"])
        self.assertTrue(any("Cầu Giấy" in m["content"] for m in messages))
