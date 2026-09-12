# -*- coding: utf-8 -*-
"""Độ gần chức danh — chiều duy nhất LLM được góp vào điểm.

Ba tính chất phải giữ, vì chính chúng là lý do việc mở cửa này chấp nhận được:

1. **Tái lập được** — lượt tìm thứ hai không gọi LLM nữa, và cho đúng kết quả cũ.
2. **Không nhìn thấy con người** — LLM chỉ nhận cặp chức danh.
3. **Hỏng thì lùi, không sai** — không gọi được LLM thì về so khớp chuỗi và nói rõ.
"""
import json
from unittest import mock

from ai.providers import Completion
from core.models import Edge, SourceRecord
from django.test import TestCase
from people import ingest
from people.models import Person

from . import scoring, semantic
from .models import TitleSimilarity


def llm(results):
    calls = []

    def fake(messages, **kwargs):
        calls.append(messages[-1]["content"])
        return Completion(text=json.dumps({"results": results}, ensure_ascii=False),
                          provider="fake", model="fake-1")

    fake.calls = calls
    return fake


class WarmTest(TestCase):
    def test_cham_truoc_va_nho_lai(self):
        fake = llm([
            {"title": "BI Developer", "score": 0.8,
             "reason": "cùng làm báo cáo và dashboard"},
            {"title": "Data Engineer", "score": 0.5, "reason": "cùng lĩnh vực dữ liệu"},
        ])
        with mock.patch("talent.semantic.complete", side_effect=fake):
            semantic.warm("Data Analyst", ["BI Developer", "Data Engineer"])

        self.assertEqual(TitleSimilarity.objects.count(), 2)
        row = semantic.lookup("Data Analyst", "BI Developer")
        self.assertEqual(row.score, 0.8)
        self.assertIn("dashboard", row.reason)

    def test_luot_sau_KHONG_goi_lai_LLM(self):
        """Tái lập được: cùng một tìm kiếm phải cho cùng một thứ tự, mãi mãi."""
        fake = llm([{"title": "BI Developer", "score": 0.8, "reason": "x"}])
        with mock.patch("talent.semantic.complete", side_effect=fake) as goi:
            semantic.warm("Data Analyst", ["BI Developer"])
            semantic.warm("Data Analyst", ["BI Developer"])
        self.assertEqual(goi.call_count, 1)

    def test_chi_hoi_nhung_cap_CON_THIEU(self):
        TitleSimilarity.objects.create(needed="data analyst",
                                       candidate="bi developer", score=0.8)
        fake = llm([{"title": "Data Engineer", "score": 0.5, "reason": "x"}])
        with mock.patch("talent.semantic.complete", side_effect=fake):
            semantic.warm("Data Analyst", ["BI Developer", "Data Engineer"])
        self.assertNotIn("BI Developer", fake.calls[0])
        self.assertIn("Data Engineer", fake.calls[0])

    def test_LLM_chi_nhin_thay_CHUC_DANH(self):
        """Nó không biết ứng viên tên gì, bao nhiêu tuổi, học ở đâu — nên không
        có đường nào để thiên lệch theo những thứ đó."""
        fake = llm([{"title": "BI Developer", "score": 0.8, "reason": "x"}])
        with mock.patch("talent.semantic.complete", side_effect=fake):
            semantic.warm("Data Analyst", ["BI Developer"])
        prompt = fake.calls[0]
        self.assertIn("BI Developer", prompt)
        self.assertIn("Data Analyst", prompt)
        self.assertNotIn("@", prompt)          # không email
        self.assertNotIn("09", prompt)         # không số điện thoại

    def test_gop_bien_the_go_khac_nhau(self):
        fake = llm([{"title": "BI Developer", "score": 0.8, "reason": "x"}])
        with mock.patch("talent.semantic.complete", side_effect=fake):
            semantic.warm("Data Analyst", ["BI Developer"])
        self.assertIsNotNone(semantic.lookup("  DATA   ANALYST ", "bi developer"))

    def test_diem_thang_100_duoc_doi_ve_0_1(self):
        fake = llm([{"title": "BI Developer", "score": 80, "reason": "x"}])
        with mock.patch("talent.semantic.complete", side_effect=fake):
            semantic.warm("Data Analyst", ["BI Developer"])
        self.assertEqual(semantic.lookup("Data Analyst", "BI Developer").score, 0.8)

    def test_bo_chuc_danh_MO_HINH_TU_THEM(self):
        """Nhận bừa nghĩa là để mô hình tự bịa ứng viên vào bộ nhớ."""
        fake = llm([
            {"title": "BI Developer", "score": 0.8, "reason": "x"},
            {"title": "Giám đốc Công nghệ", "score": 0.9, "reason": "bịa"},
        ])
        with mock.patch("talent.semantic.complete", side_effect=fake):
            semantic.warm("Data Analyst", ["BI Developer"])
        self.assertEqual(TitleSimilarity.objects.count(), 1)

    def test_LLM_hong_thi_khong_ghi_gi(self):
        with mock.patch("talent.semantic.complete",
                        side_effect=RuntimeError("bị giới hạn tốc độ")):
            semantic.warm("Data Analyst", ["BI Developer"])
        self.assertEqual(TitleSimilarity.objects.count(), 0)

    def test_tra_ve_rac_thi_khong_ghi_gi(self):
        def rac(messages, **kwargs):
            return Completion(text="xin chào", provider="f", model="f")

        with mock.patch("talent.semantic.complete", side_effect=rac):
            semantic.warm("Data Analyst", ["BI Developer"])
        self.assertEqual(TitleSimilarity.objects.count(), 0)

    def test_khong_co_chuc_danh_can_tuyen_thi_khong_goi(self):
        with mock.patch("talent.semantic.complete") as goi:
            semantic.warm("", ["BI Developer"])
        goi.assert_not_called()


class ScoringWithSemanticTest(TestCase):
    """Chiều `title` phải dùng bộ nhớ khi có, và lùi về so chữ khi không."""

    def setUp(self):
        edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        for ten, chuc_danh in (("An", "BI Developer"),
                               ("Bình", "Senior Data Analyst")):
            SourceRecord.objects.create(
                edge=edge, entity_type="source_record",
                entity_key=f"topcv|a|{ten}", content_hash=f"h{ten}",
                payload={"source": "topcv", "fullname": f"Nguyễn Văn {ten}",
                         "email": f"{ten}@x.vn", "current_title": chuc_danh,
                         "position": chuc_danh, "skills": "SQL",
                         "applied_ts": "2026-08-01 09:00:00"})
        ingest.resolve_pending()

    def _dim(self, person, key="title"):
        result = scoring.score_person(person, {"title": "Data Analyst"})
        return next(d for d in result["dimensions"] if d["key"] == key)

    def test_bao_ham_chuoi_van_duoc_1_diem_khong_can_LLM(self):
        binh = Person.objects.get(display_name__contains="Bình")
        with mock.patch("talent.semantic.complete") as goi:
            self.assertEqual(self._dim(binh)["score"], 1.0)
        goi.assert_not_called()

    def test_KHONG_co_bo_nho_thi_BI_Developer_bi_cham_oan(self):
        """Đây là lỗi cũ, giữ lại thành bài kiểm thử để thấy rõ vấn đề."""
        an = Person.objects.get(display_name__contains="An")
        self.assertEqual(self._dim(an)["score"], 0.0)

    def test_CO_bo_nho_thi_BI_Developer_duoc_cham_dung(self):
        TitleSimilarity.objects.create(
            needed="data analyst", candidate="bi developer", score=0.8,
            reason="cùng làm báo cáo và dashboard")
        an = Person.objects.get(display_name__contains="An")
        dimension = self._dim(an)
        self.assertEqual(dimension["score"], 0.8)
        self.assertIn("dashboard", dimension["fact"])

    def test_lui_ve_so_chu_thi_NOI_RO_la_moi_so_chu(self):
        """Không nói ra thì người đọc tưởng hệ thống đã hiểu nghề mà vẫn chấm thấp."""
        edge = Edge.objects.get(edge_id="e1")
        SourceRecord.objects.create(
            edge=edge, entity_type="source_record", entity_key="topcv|a|C",
            content_hash="hC",
            payload={"source": "topcv", "fullname": "Nguyễn Văn C",
                     "email": "c@x.vn", "current_title": "Data Engineer",
                     "position": "Data Engineer", "skills": "SQL",
                     "applied_ts": "2026-08-01 09:00:00"})
        ingest.resolve_pending()

        c = Person.objects.get(display_name__contains="Văn C")
        dimension = self._dim(c)
        self.assertGreater(dimension["score"], 0)
        self.assertIn("so chữ", dimension["fact"])

    def test_dau_ngoac_khong_duoc_lam_ca_danh_sach_tut_ve_0(self):
        """Tiêu đề JD hay có dạng "... (Data Analyst)". Không bỏ dấu câu thì
        "analyst)" không khớp "analyst" — cả bảng điểm hỏng vì một dấu ngoặc."""
        an = Person.objects.get(display_name__contains="Bình")   # Senior Data Analyst
        result = scoring.score_person(
            an, {"title": "Chuyên viên Phân tích Dữ liệu (Data Analyst)"})
        dimension = next(d for d in result["dimensions"] if d["key"] == "title")
        self.assertGreater(dimension["score"], 0)

    def test_cap_bac_khong_lam_giam_diem_khop_chu(self):
        """Số năm kinh nghiệm đã chấm riêng; trừ "Senior" lần nữa là phạt oan."""
        binh = Person.objects.get(display_name__contains="Bình")
        result = scoring.score_person(binh, {"title": "Data Analyst"})
        dimension = next(d for d in result["dimensions"] if d["key"] == "title")
        self.assertEqual(dimension["score"], 1.0)

    def test_diem_TONG_van_la_tong_co_trong_so(self):
        """Mở cửa cho LLM ở một chiều không được biến điểm thành hộp đen."""
        TitleSimilarity.objects.create(
            needed="data analyst", candidate="bi developer", score=0.8)
        an = Person.objects.get(display_name__contains="An")
        result = scoring.score_person(an, {"title": "Data Analyst"})

        # Điểm tổng kết hợp độ liên quan nội dung và độ tươi/liên hệ
        relevance_dims = [d for d in result["dimensions"] if d["key"] not in ("freshness", "reachability")]
        support_dims = [d for d in result["dimensions"] if d["key"] in ("freshness", "reachability")]
        rw = sum(d["weight"] for d in relevance_dims) or 1.0
        relevance = sum(d["score"] * d["weight"] for d in relevance_dims) / rw
        sw = sum(d["weight"] for d in support_dims) or 1.0
        support = sum(d["score"] * d["weight"] for d in support_dims) / sw
        ky_vong = relevance * (0.75 + 0.25 * support)
        self.assertAlmostEqual(result["score"], ky_vong, places=3)
