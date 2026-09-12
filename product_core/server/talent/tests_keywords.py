# -*- coding: utf-8 -*-
"""Đường lui dò từ khoá — thứ giữ cho hệ thống dùng được khi LLM bận.

Khoá LLM miễn phí giới hạn ~15 lượt/phút, và trong lúc dựng dự án này nó dính
giới hạn ba lần trong một buổi. Nên đây không phải nhánh phòng xa hiếm gặp; nó
là nhánh sẽ chạy thật, kể cả ngày demo.
"""
from unittest import mock

from core.models import Edge, SourceRecord
from django.test import TestCase
from people import ingest

from . import hiring_need, keywords


class KeywordCriteriaTest(TestCase):
    def setUp(self):
        edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        mau = [
            ("An", "Data Analyst", "SQL, Python, Power BI", "Hà Nội", "4 năm"),
            ("Bình", "Backend Engineer", "Java, Kafka", "Hồ Chí Minh", "8 năm"),
        ]
        for ten, vitri, ky_nang, tp, so_nam in mau:
            SourceRecord.objects.create(
                edge=edge, entity_type="source_record",
                entity_key=f"topcv|a|{ten}", content_hash=f"h{ten}",
                payload={"source": "topcv", "account": "a", "cv_id": ten,
                         "fullname": f"Nguyễn Văn {ten}", "email": f"{ten}@x.vn",
                         "current_title": vitri, "position": vitri,
                         "skills": ky_nang, "city": tp, "years_experience": so_nam,
                         "applied_ts": "2026-08-01 09:00:00"})
        ingest.resolve_pending()

    def test_tu_vung_lay_TU_CSDL_chu_khong_viet_cung(self):
        skills, locations = keywords.vocabulary()
        self.assertIn("SQL", skills)
        self.assertIn("Kafka", skills)
        self.assertIn("Hà Nội", locations)

    def test_do_duoc_ky_nang_va_noi_o(self):
        criteria = keywords.criteria_from_text(
            "Cần người biết SQL và Python, làm tại Hà Nội")
        self.assertEqual(sorted(criteria["skills"]), ["Python", "SQL"])
        self.assertEqual(criteria["location"], "Hà Nội")

    def test_khong_bia_ky_nang_khong_ai_co(self):
        """Tiêu chí rút ra phải là thứ TÌM ĐƯỢC người, nếu không lùi cũng vô ích."""
        criteria = keywords.criteria_from_text("Yêu cầu COBOL và Fortran")
        self.assertNotIn("skills", criteria)

    def test_lay_moc_nam_nho_nhat(self):
        criteria = keywords.criteria_from_text("Tối thiểu 3 năm, ưu tiên 7 năm")
        self.assertEqual(criteria["min_years"], 3)

    def test_bo_qua_con_so_vo_ly(self):
        criteria = keywords.criteria_from_text("Công ty thành lập 99 năm trước")
        self.assertNotIn("min_years", criteria)

    def test_lay_phan_trong_ngoac_lam_tieu_chi_tim_kiem(self):
        """CV phần lớn ghi chức danh tiếng Anh, nên "(Data Analyst)" mới là thứ
        khớp được — cả cụm tiếng Việt chỉ hợp làm TÊN vị trí."""
        self.assertEqual(
            keywords.title_for_criteria("Chuyên viên Phân tích Dữ liệu (Data Analyst)"),
            "Data Analyst")

    def test_ngoac_khong_phai_chuc_danh_thi_giu_nguyen_ca_cum(self):
        for headline in ("Chuyên viên Dữ liệu (2 vị trí)",
                         "Chuyên viên Dữ liệu (HN & HCM)",
                         "Chuyên viên Dữ liệu (làm việc toàn thời gian tại văn phòng)"):
            self.assertEqual(keywords.title_for_criteria(headline), headline)

    def test_khong_co_ngoac_thi_giu_nguyen(self):
        self.assertEqual(keywords.title_for_criteria("Data Analyst"), "Data Analyst")

    def test_dong_dau_lam_ten_vi_tri(self):
        self.assertEqual(
            keywords.first_line_title("  - Chuyên viên Dữ liệu\n\nMô tả: ..."),
            "Chuyên viên Dữ liệu")


class SearchFallbackTest(KeywordCriteriaTest):
    def test_LLM_ban_thi_van_TIM_RA_nguoi(self):
        """Nếu chỉ ném cả câu vào tìm-chữ-tự-do thì kết quả là 0 người.

        Không hồ sơ nào chứa nguyên văn câu hỏi. Đó là kiểu hỏng im lặng tệ
        nhất: hệ thống trông như đang chạy, chỉ là không tìm thấy ai.
        """
        with mock.patch("talent.hiring_need.complete",
                        side_effect=RuntimeError("bị giới hạn tốc độ")):
            need = hiring_need.parse("Tìm Data Analyst ở Hà Nội biết SQL và Python")

        self.assertTrue(need.fallback)
        self.assertNotIn("text", need.criteria)
        self.assertEqual(need.criteria["location"], "Hà Nội")

        from . import search as search_module
        total, _people = search_module.search(
            skills=need.criteria["skills"], location=need.criteria["location"])
        self.assertGreater(total, 0)

    def test_khong_do_duoc_gi_thi_moi_dung_ca_cau(self):
        with mock.patch("talent.hiring_need.complete",
                        side_effect=RuntimeError("bận")):
            need = hiring_need.parse("tìm ai đó giỏi giỏi một chút")
        self.assertEqual(need.criteria, {"text": "tìm ai đó giỏi giỏi một chút"})
