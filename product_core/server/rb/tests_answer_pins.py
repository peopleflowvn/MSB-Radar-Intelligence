# -*- coding: utf-8 -*-
"""Growth: ghim tất định — tên riêng, điều kiện có cấu trúc, cực trị toàn kho."""
import json
import re
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from people.models import Person, Relationship, Signal

from .answer import engine
from .answer import resolve as resolve_stage
from .answer import retrieve as retrieve_stage
from .answer.aggregate import RECENCY_KEY, aggregate
from .answer.judge import Judgement
from .answer.plan import ProspectPlan
from .models import OpportunitySuggestion, ProductInterest, RBProfile


class FakeCompletion:
    def __init__(self, text):
        self.text, self.provider, self.model, self.truncated = text, "fake", "fake-1", False


def _days_ago(days):
    return timezone.now() - timezone.timedelta(days=days)


def _customer(name, *, location="", products=(), post_days=None, phone="0900000000"):
    person = Person.objects.create(display_name=name, location=location,
                                   primary_phone=phone, is_applicant=False)
    profile = RBProfile.objects.create(person=person)
    for product in products:
        ProductInterest.objects.create(profile=profile, product=product, confidence=0.8,
                                       observed_at=_days_ago(10))
    if post_days is not None:
        from social.models import SocialPost
        SocialPost.objects.create(person=person, content=f"{name} hỏi về vay vốn",
                                  posted_at=_days_ago(post_days),
                                  external_id=f"pin-{person.pk}")
    return person


def engine_caller(plan_payload, *, relevant=True):
    """Model giả: ① trả `plan_payload`; ③ đánh giá mọi khách được gửi là `relevant`."""
    plan_payload = {"suy_luan": "t", "do_tin_cay": 0.95, **plan_payload}

    def caller(messages, **kwargs):
        body = messages[-1]["content"]
        if "DANH SÁCH KHÁCH HÀNG" in body:
            rows = []
            for pid, first_passage in re.findall(r"id=(\d+).*?\n\[1\] \([^)]*\) (.{0,60})", body):
                rows.append({"id": int(pid), "thoa": relevant, "do_tin": 0.9,
                             "vi_sao": "đọc được",
                             "trich_dan": [{"doan": 1, "nguyen_van": first_passage[:40]}]})
            return FakeCompletion(json.dumps({"ket_qua": rows}, ensure_ascii=False))
        return FakeCompletion(json.dumps(plan_payload, ensure_ascii=False))
    return caller


def stream_text(text="ok"):
    def streamer(messages, **kwargs):
        yield {"type": "answer", "text": text}
        yield {"type": "done", "completion": FakeCompletion(text)}
    return streamer


class NamedCustomerTest(TestCase):
    """Tên là định danh: lần này lọt, lần sau rớt là lỗi, không phải nhiễu."""

    def setUp(self):
        self.an = _customer("Nguyễn Văn An", post_days=3)
        self.binh = _customer("Trần Thị Bình", post_days=3)
        for i in range(30):
            _customer(f"Khách Nền {i}", post_days=1)

    def test_goi_ten_trong_cau_hoi_duoc_ghim(self):
        ids = resolve_stage.named_customers(ProspectPlan(), "so sánh Nguyễn Văn An và Trần Thị Bình")
        self.assertEqual(set(ids), {self.an.pk, self.binh.pk})

    def test_ung_vien_trung_ten_KHONG_bi_ghim_vao_cau_hoi_ve_khach(self):
        ung_vien = Person.objects.create(display_name="Nguyễn Văn An")   # Talent, không có dữ liệu RB
        ids = resolve_stage.named_customers(ProspectPlan(), "khách Nguyễn Văn An thế nào")
        self.assertIn(self.an.pk, ids)
        self.assertNotIn(ung_vien.pk, ids)

    def test_ten_Viet_la_tu_chuc_nang_khong_bi_cat(self):
        """"Hằng", "Anh", "Chi" sau khi bỏ dấu trùng từ chức năng — vẫn phải khớp."""
        hang = _customer("Mai Thu Hằng", post_days=2)
        ids = resolve_stage.named_customers(
            ProspectPlan(search_queries=["Mai Thu Hằng"]), "khách Mai Thu Hằng")
        self.assertIn(hang.pk, ids)

    def test_so_sanh_theo_ten_chi_doc_dung_hai_nguoi(self):
        seen = {}
        real = retrieve_stage.retrieve

        def spy(plan, **kwargs):
            out = real(plan, **kwargs)
            seen["ids"] = [c.person_id for c in out]
            return out

        with mock.patch.object(retrieve_stage, "retrieve", spy):
            engine.answer("so sánh Nguyễn Văn An và Trần Thị Bình",
                          complete_fn=engine_caller({
                              "shape": "compare", "search_queries": ["vay vốn"],
                              "information_need": "so sánh Nguyễn Văn An và Trần Thị Bình"}),
                          stream_fn=stream_text())
        self.assertEqual(set(seen["ids"]), {self.an.pk, self.binh.pk})

    def test_goi_ten_khach_khong_lien_he_van_bi_chan(self):
        Relationship.objects.create(person=self.an, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        got = [c.person_id for c in retrieve_stage.retrieve(
            ProspectPlan(shape="compare"), pinned_ids=[self.an.pk, self.binh.pk],
            pool=2)]
        self.assertNotIn(self.an.pk, got)


class StructuredPinTest(TestCase):
    def test_moi_dieu_kien_co_cau_truc_thi_ghim_dung_nguoi_thoa(self):
        dung = _customer("HN Mua Nhà", location="Hà Nội", products=["mortgage"])
        _customer("ĐN Mua Nhà", location="Đà Nẵng", products=["mortgage"])
        _customer("HN Không", location="Hà Nội")
        pins = resolve_stage.structured_pins(
            ProspectPlan(must_have=["ở Hà Nội", "quan tâm vay mua nhà"]))
        self.assertEqual(pins, [dung.pk])

    def test_con_dieu_kien_can_doc_thi_KHONG_ghim(self):
        """Ghim người chỉ thoả "ở Hà Nội" cho câu "ở Hà Nội và mới kết hôn" là chiếm chỗ."""
        _customer("HN", location="Hà Nội")
        self.assertEqual(resolve_stage.structured_pins(
            ProspectPlan(must_have=["ở Hà Nội", "mới kết hôn"])), [])


class SuperlativeTest(TestCase):
    def test_nhan_ra_cau_cuc_tri(self):
        self.assertEqual(resolve_stage.superlative_attr(ProspectPlan(), "khách có tín hiệu mới nhất"),
                         resolve_stage.ATTR_RECENCY)
        self.assertEqual(resolve_stage.superlative_attr(ProspectPlan(), "khách đáng gọi nhất tuần này"),
                         resolve_stage.ATTR_PRIORITY)
        self.assertIsNone(resolve_stage.superlative_attr(ProspectPlan(), "khách cần vay mua nhà"))

    def test_moi_nhat_la_moi_nhat_TOAN_kho_khong_phai_trong_mau(self):
        cu = _customer("Cũ", post_days=200)
        moi = _customer("Mới", post_days=1)
        vua = _customer("Vừa", post_days=30)
        ids = resolve_stage.superlative_ids(ProspectPlan(), resolve_stage.ATTR_RECENCY, limit=2)
        self.assertEqual(ids, [moi.pk, vua.pk])
        self.assertNotIn(cu.pk, ids)

    def test_dang_goi_nhat_theo_diem_de_xuat_dang_mo(self):
        thap = _customer("Thấp")
        cao = _customer("Cao")
        for person, score in ((thap, 40.0), (cao, 90.0)):
            OpportunitySuggestion.objects.create(person=person, product="mortgage",
                                                 priority_score=score)
        self.assertEqual(resolve_stage.superlative_ids(
            ProspectPlan(), resolve_stage.ATTR_PRIORITY, limit=1), [cao.pk])

    def test_cuc_tri_khong_lot_khach_khong_lien_he(self):
        moi = _customer("Mới Nhưng DNC", post_days=0)
        Relationship.objects.create(person=moi, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        _customer("Hợp Lệ", post_days=5)
        self.assertNotIn(moi.pk, resolve_stage.superlative_ids(
            ProspectPlan(), resolve_stage.ATTR_RECENCY, limit=5))

    def test_aggregate_giu_thu_tu_moi_nhat_khong_xep_lai_theo_diem(self):
        a = _customer("Điểm Cao Tín Hiệu Cũ", location="Hà Nội")
        b = _customer("Điểm Thấp Tín Hiệu Mới", phone="")
        rows = [Judgement(person_id=a.pk, name="a", relevant=True, confidence=0.9,
                          evidence=[{"quote": "x"}], freshest_days=60),
                Judgement(person_id=b.pk, name="b", relevant=True, confidence=0.9,
                          evidence=[{"quote": "x"}], freshest_days=1)]
        chosen, _near, stats = aggregate(ProspectPlan(sort_by={"key": RECENCY_KEY}), rows)
        self.assertEqual([r.person_id for r in chosen], [b.pk, a.pk])
        self.assertEqual(stats["sorted_by"]["key"], "recency")


class NamePhraseSharedWithTalentTest(SimpleTestCase):
    def test_talent_van_dung_dung_ham_tach_ten(self):
        from core.answer import names
        from talent.answer import resolve as talent_resolve
        self.assertIs(talent_resolve._phrases, names.phrases)


class JudgeConnectionTest(TestCase):
    """Kết nối CSDL được đóng ở LUỒNG PHỤ của từng lô, không ở luồng gọi.

    Không kiểm bằng cách mở giao dịch rồi truy vấn tiếp: SQLite bộ nhớ trong môi
    trường test cố ý bỏ qua `close()`, nên phép kiểm đó xanh cả với bản lỗi (đã
    thử). Kiểm thẳng luồng nào gọi `close()`.
    """

    def test_dong_ket_noi_trong_luong_phu_moi_lo_mot_lan(self):
        import threading
        from django.db import connections
        from .answer import judge as judge_stage
        from .answer.evidence import Candidate, Passage

        def caller(messages, **kwargs):
            ids = [int(x) for x in re.findall(r"id=(\d+)", messages[-1]["content"])]
            return FakeCompletion(json.dumps({"ket_qua": [
                {"id": pid, "thoa": False} for pid in ids]}))

        candidates = [Candidate(i, f"K{i}", passages=[Passage(i, "nội dung đủ dài để đọc", "profile")])
                      for i in range(1, 17)]
        closers = []
        main = threading.get_ident()
        # `connection` là proxy; lớp thật là DatabaseWrapper — mọi luồng dùng chung lớp.
        with mock.patch.object(type(connections["default"]), "close", autospec=True,
                               side_effect=lambda *a, **k: closers.append(threading.get_ident())):
            report = judge_stage.judge(ProspectPlan(), candidates, complete_fn=caller, batch_size=4)
        self.assertEqual(report.batches, 4)
        self.assertEqual(len(closers), 4)
        self.assertNotIn(main, closers)
