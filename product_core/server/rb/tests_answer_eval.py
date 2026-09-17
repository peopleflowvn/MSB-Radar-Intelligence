# -*- coding: utf-8 -*-
"""`prospect_answer_eval`: phép kiểm phải BẮT ĐƯỢC vi phạm, và lệnh không để lại dấu vết.

Một bộ kiểm chỉ từng thấy câu trả lời tốt thì không ai biết nó có bắt được câu
trả lời xấu không. Mỗi test ở đây dựng đúng một vi phạm và đòi phép kiểm tương
ứng báo trượt.
"""
import json
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from people.models import Person, Relationship, Signal

from .answer.engine import AnswerResult
from .management.commands.prospect_answer_eval import QUESTIONS, check
from .models import ProductInterest, RBOpportunity, RBProfile


def _customer(name, *, owner=None, location="", products=()):
    person = Person.objects.create(display_name=name, location=location, is_applicant=False)
    profile = RBProfile.objects.create(person=person, sales_owner=owner)
    for product in products:
        ProductInterest.objects.create(profile=profile, product=product, confidence=0.8,
                                       observed_at=timezone.now())
    return person


def _result(text="Một câu trả lời đủ dài để được chấm điểm.", people=(), trace=None, **kw):
    return AnswerResult(text=text, people=list(people), trace=trace or {}, **kw)


class ChecksCatchViolationsTest(TestCase):
    def setUp(self):
        self.rm = get_user_model().objects.create_user("eval-rm")
        self.other = get_user_model().objects.create_user("eval-other")
        self.khach = _customer("Khách Hợp Lệ", owner=self.rm)

    def test_cau_tra_loi_sach_thi_dat(self):
        checks, problems = check({"q": "x"}, _result(people=[
            {"person_id": self.khach.pk, "name": "Khách Hợp Lệ"}]), user=self.rm)
        self.assertTrue(all(checks.values()), problems)

    def test_bat_khach_khong_lien_he(self):
        Relationship.objects.create(person=self.khach, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        checks, _ = check({"q": "x"}, _result(people=[{"person_id": self.khach.pk}]))
        self.assertFalse(checks["no_do_not_contact"])

    def test_bat_ung_vien_tuyen_dung_lot_vao(self):
        ung_vien = Person.objects.create(display_name="Ứng Viên")
        checks, _ = check({"q": "x"}, _result(people=[{"person_id": ung_vien.pk}]))
        self.assertFalse(checks["customers_only"])

    def test_bat_khach_nguoi_khac_trong_cau_khach_cua_toi(self):
        cua_nguoi_khac = _customer("Của Người Khác", owner=self.other)
        checks, _ = check({"q": "x", "portfolio": True},
                          _result(people=[{"person_id": cua_nguoi_khac.pk}]), user=self.rm)
        self.assertFalse(checks["portfolio_scope"])

    def test_bat_so_lien_he_con_nguyen(self):
        checks, _ = check({"q": "x"}, _result(text="Gọi cho khách qua 0901234567 nhé anh."))
        self.assertFalse(checks["no_contacts"])

    def test_bat_so_dem_chinh_xac_khong_khop_sql(self):
        _customer("A", location="Hà Nội", products=["mortgage"])
        plan = {"shape": "count", "must_have": ["ở Hà Nội", "quan tâm vay mua nhà"]}
        lie = _result(text="Có **99** khách hàng thoả: ở Hà Nội.",
                      trace={"plan": plan, "count": {"exact": True, "matched": 99}})
        checks, _ = check({"q": "x", "count": "exact"}, lie)
        self.assertFalse(checks["count_exact_matches"])
        truth = _result(text="Có **1** khách hàng thoả: ở Hà Nội.",
                        trace={"plan": plan, "count": {"exact": True, "matched": 1}})
        checks, _ = check({"q": "x", "count": "exact"}, truth)
        self.assertTrue(checks["count_exact_matches"])

    def test_bat_uoc_luong_khong_dan_nhan(self):
        checks, _ = check({"q": "x", "count": "estimate"}, _result(
            text="Có 12 khách mới kết hôn trong kho của anh chị.",
            trace={"count": {"exact": False}}))
        self.assertFalse(checks["count_estimate_label"])

    def test_bat_cau_lenh_noi_da_gui_hoac_len_tao_co_hoi(self):
        before = RBOpportunity.objects.count()
        checks, _ = check({"q": "x", "command": "draft"},
                          _result(text="Em đã gửi tin nhắn cho khách rồi ạ."),
                          opportunities_before=before)
        self.assertFalse(checks["command_sends_nothing"])
        RBOpportunity.objects.create(person=self.khach, product="mortgage")
        checks, _ = check({"q": "x", "command": "draft"},
                          _result(text="Đã soạn 1 bản nháp. Chưa gửi cho ai."),
                          opportunities_before=before)
        self.assertFalse(checks["command_sends_nothing"])

    def test_bat_trich_dan_bia(self):
        checks, _ = check({"q": "x"}, _result(
            people=[{"person_id": self.khach.pk, "name": "Khách Hợp Lệ"}],
            all_sources=[{"n": 1, "person_id": self.khach.pk,
                          "snippet": "một câu không hề có trong bằng chứng nào"}]))
        self.assertFalse(checks["citations_real"])

    def test_bat_chot_bo_du_lieu(self):
        checks, _ = check({"q": "x", "knows_store": True},
                          _result(text="Xin lỗi, tôi không có dữ liệu về kho khách hàng."))
        self.assertFalse(checks["knows_store"])


class FakeCompletion:
    def __init__(self, text):
        self.text, self.provider, self.model, self.truncated = text, "fake", "fake-1", False


class CommandLeavesNoTraceTest(TransactionTestCase):
    """Chạy trên production: không được để lại hội thoại hay cơ hội nào."""

    def test_chay_cau_hoi_tiep_va_cau_lenh_roi_hoan_tac(self):
        import re
        from ai.models import AssistantThread
        from social.models import SocialPost
        from rb import answer_views

        rm = get_user_model().objects.create_user("eval-trace-rm")
        khach = _customer("Cần Vay Nhà", products=["mortgage"])
        SocialPost.objects.create(person=khach, content="em đang cần vay mua nhà gấp",
                                  posted_at=timezone.now(), external_id="eval-trace-1")
        draft_index = next(i for i, c in enumerate(QUESTIONS, 1) if c.get("command") == "draft")

        def model(messages, **kwargs):
            body = messages[-1]["content"]
            if "DANH SÁCH KHÁCH HÀNG" in body:
                ids = [int(x) for x in re.findall(r"id=(\d+)", body)]
                return FakeCompletion(json.dumps({"ket_qua": [
                    {"id": pid, "thoa": True, "do_tin": 0.9, "vi_sao": "tự viết cần vay",
                     "trich_dan": [{"doan": 1, "nguyen_van": "em đang cần vay mua nhà gấp"}]}
                    for pid in ids]}, ensure_ascii=False))
            shape = "action" if "soạn" in body else "find_prospects"
            return FakeCompletion(json.dumps({"suy_luan": "t", "do_tin_cay": 0.95,
                                              "shape": shape, "search_queries": ["vay mua nhà"]},
                                             ensure_ascii=False))

        def streamer(messages, **kwargs):
            yield {"type": "answer", "text": "Cần Vay Nhà cần vay mua nhà [1]."}
            yield {"type": "done", "completion": FakeCompletion("Cần Vay Nhà cần vay mua nhà [1].")}

        threads_during_run = []
        real_persist = answer_views._persist

        def spy_persist(*args, **kwargs):
            real_persist(*args, **kwargs)
            threads_during_run.append(AssistantThread.objects.count())

        with mock.patch("rb.answer.plan.complete", model),                 mock.patch("rb.answer.judge.complete", model),                 mock.patch("rb.answer.engine.router_stream", streamer),                 mock.patch("rb.answer_views._persist", spy_persist),                 mock.patch("rb.outreach.complete",
                           return_value=FakeCompletion("Chào anh, em bên MSB muốn trao đổi về khoản vay mua nhà.")):
            out = StringIO()
            call_command("prospect_answer_eval", "--as-user", rm.username,
                         "--only", str(draft_index), stdout=out)
        # Câu lệnh thật sự chạy và đạt (có danh sách, soạn nháp, nói "chưa gửi").
        self.assertIn("Đạt 1/1", out.getvalue(), out.getvalue())
        # Lượt đầu THẬT SỰ được ghi trong lúc chạy…
        self.assertEqual(threads_during_run, [1])
        # …và không còn gì sau khi lệnh xong.
        self.assertEqual(AssistantThread.objects.count(), 0)
        self.assertEqual(RBOpportunity.objects.count(), 0)
