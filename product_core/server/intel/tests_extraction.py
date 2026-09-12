# -*- coding: utf-8 -*-
"""Pipeline Edge-first + AI-fill-gaps (Master Plan §7, §21.6)."""
from django.test import TestCase

from core.models import Edge, SourceRecord
from people.models import Document, Person

from . import seeds
from .extraction import coverage_summary, run_for_person
from .facts import current_facts
from .models import ExtractedFact


class FakeUsage:
    prompt_tokens = 120
    completion_tokens = 40


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.provider = "fake"
        self.model = "fake-1"
        self.usage = FakeUsage()


class FakeAdapter:
    def __init__(self, text):
        self._text = text

    def complete(self, request):
        return FakeResponse(self._text)


class ExtractionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seeds.seed_all()

    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        self.person = Person.objects.create(display_name="Nguyễn Văn An")
        SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record", entity_key="topcv|a|1",
            content_hash="h1", person=self.person,
            payload={"source": "topcv", "fullname": "Nguyễn Văn An",
                     "current_title": "Data Analyst", "position": "Data Analyst",
                     "last_company": "Ngân hàng ABC", "city": "TP.HCM",
                     "skills": "SQL, Power BI, Python", "years_experience": "4 năm",
                     "job_level": "Senior", "applied_ts": "2026-08-01 09:00:00"})

    def test_edge_mapping_records_facts_and_canonicalises(self):
        run = run_for_person(self.person, use_ai=False)
        self.assertEqual(run.status, run.STATUS_DONE)
        self.assertGreaterEqual(run.coverage["edge"], 6)
        self.assertTrue(run.coverage["reused_no_ai"])
        self.assertEqual(run.coverage["ai_calls"], 0)

        current = {f.field: f for f in current_facts(self.person)}
        self.assertEqual(current["city"].canonical_code, "VN-SG")
        self.assertEqual(current["current_title"].canonical_code, "data-analyst")
        self.assertEqual(current["seniority"].canonical_code, "senior")
        self.assertEqual(
            {f.canonical_code for f in current_facts(self.person, "skills")},
            {"sql", "power-bi", "python"})

    def test_topcv_position_is_applied_position_not_current_title(self):
        """Payload TopCV thật: `position` = vị trí ứng tuyển, `current_title` rỗng."""
        p = Person.objects.create(display_name="Nông Thị Quỳnh Anh")
        SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record", entity_key="topcv|x|54679683",
            content_hash="hx", person=p,
            payload={"source": "topcv", "fullname": "nông Thị Quỳnh Anh",
                     "email": "anhntq77@gmail.com", "phone": "08.5569.2599",
                     "position": "Chuyên viên chính Vận hành đối soát - KVH - MSB - 3K061",
                     "current_title": "", "city": "", "district": "", "skills": "",
                     "birth_year": "", "applied_at": "30/08/2026 15:31",
                     "applied_ts": "2026-08-30 15:31:00"})
        run = run_for_person(p, use_ai=False)
        self.assertEqual(run.status, run.STATUS_DONE)
        current = {f.field: f for f in current_facts(p)}
        self.assertIn("applied_position", current)
        self.assertIn("KVH", current["applied_position"].raw_value)
        self.assertNotIn("current_title", current)          # KHÔNG lấy từ `position`
        self.assertEqual(current["applied_date"].raw_value, "2026-08-30")
        self.assertEqual(current["source"].canonical_code or "", "")   # 'topcv' -> alias chờ

    def test_is_idempotent(self):
        run_for_person(self.person, use_ai=False)
        n1 = ExtractedFact.objects.filter(person=self.person).count()
        run_for_person(self.person, use_ai=False)
        self.assertEqual(ExtractedFact.objects.filter(person=self.person).count(), n1)

    def test_does_not_reparse_cv(self):
        doc = Document.objects.create(
            person=self.person, sha256="cv1", document_type="cv",
            parsed_text="Tốt nghiệp Đại học Bách Khoa, ngành Khoa học Máy tính. "
                        "Thành thạo tiếng Anh.",
            parse_status=Document.PARSE_DONE)
        run_for_person(
            self.person, use_ai=True,
            adapter=FakeAdapter('{"education_level": {"value": "Đại học", '
                                '"evidence": "Tốt nghiệp Đại học Bách Khoa", "confidence": 0.9}, '
                                '"major": {"value": "Khoa học Máy tính", "evidence": "ngành KHMT", '
                                '"confidence": 0.9}, '
                                '"languages": {"value": ["Tiếng Anh"], "evidence": "Thành thạo tiếng Anh", '
                                '"confidence": 0.9}}'))
        doc.refresh_from_db()
        self.assertEqual(doc.parse_status, Document.PARSE_DONE)   # không đụng parsing
        current = {f.field for f in current_facts(self.person)}
        self.assertIn("education_level", current)
        self.assertIn("major", current)
        edu = current_facts(self.person, "education_level").first()
        self.assertEqual(edu.canonical_code, "bachelor")
        self.assertEqual(edu.source_kind, ExtractedFact.SOURCE_AI)
        self.assertIn("Bách Khoa", edu.evidence)

    def test_fact_tu_cv_chay_thang_vao_talentprofile(self):
        """Sau extraction, fact AI bóc từ text CV phải xuất hiện ở TalentProfile
        — nguồn của tìm kiếm cấu trúc + chỉ mục ngữ nghĩa. Không có bước này thì
        "một đoạn văn bản dài" chỉ tra được bằng LIKE."""
        from talent.models import TalentProfile

        # `education` KHÔNG có trong payload Edge -> AI phải điền, rồi phải chảy
        # tiếp vào cột TalentProfile.education.
        TalentProfile.objects.create(person=self.person, education="")
        Document.objects.create(
            person=self.person, sha256="cv-proj", document_type="cv",
            parsed_text="Tốt nghiệp Đại học Ngoại thương.",
            parse_status=Document.PARSE_DONE)
        run_for_person(
            self.person, use_ai=True,
            adapter=FakeAdapter(
                '{"education_level": {"value": "Đại học", "evidence": "Ngoại thương", '
                '"confidence": 0.9}}'))

        profile = TalentProfile.objects.get(person=self.person)
        # Nhãn canonical chuẩn hoá cách viết — "Đại học" → "Cử nhân / Đại học";
        # điều cần khẳng định là cột không còn trống.
        self.assertIn("Đại học", profile.education)

    def test_tom_tat_nang_luc_tu_dong_dien_khi_ai_tu_tin(self):
        """`experience_summary` từng có gate 1.01 (không thể đạt) nên kẹt ở
        `proposed` mãi -> cột `TalentProfile.summary` rỗng toàn kho, chỉ mục ngữ
        nghĩa mất một nguồn. Gate 0.85 cho phép AI tự tin thì nhận luôn."""
        from talent.models import TalentProfile

        TalentProfile.objects.create(person=self.person, summary="")
        Document.objects.create(
            person=self.person, sha256="cv-sum", document_type="cv",
            parsed_text="Chuyên viên quan hệ khách hàng doanh nghiệp, 6 năm tại "
                        "khối SME. Thế mạnh: thẩm định, quản lý danh mục.",
            parse_status=Document.PARSE_DONE)
        run_for_person(
            self.person, use_ai=True,
            adapter=FakeAdapter(
                '{"experience_summary": {"value": "6 năm quan hệ khách hàng doanh '
                'nghiệp khối SME, mạnh thẩm định và quản lý danh mục.", '
                '"evidence": "Chuyên viên quan hệ khách hàng doanh nghiệp, 6 năm", '
                '"confidence": 0.9}}'))
        profile = TalentProfile.objects.get(person=self.person)
        self.assertIn("SME", profile.summary)

    def test_ai_only_fills_missing_fields(self):
        Document.objects.create(
            person=self.person, sha256="cv2", document_type="cv",
            parsed_text="Chức danh hiện tại: Trưởng nhóm Dữ liệu. Kỹ năng: Tableau.",
            parse_status=Document.PARSE_DONE)
        # city đã có từ Edge -> không nằm trong danh sách field gửi AI
        run = run_for_person(
            self.person, use_ai=True,
            adapter=FakeAdapter('{"city": {"value": "Hà Nội", "confidence": 0.9}, '
                                '"skills": {"value": ["Tableau"], "confidence": 0.9}}'))
        self.assertEqual(run.coverage["ai_calls"], 1)
        # AI trả city nhưng city đã có từ Edge (VN-SG) -> vẫn là VN-SG
        self.assertEqual(current_facts(self.person, "city").first().canonical_code, "VN-SG")

    def test_tolerates_non_compliant_ai_output(self):
        # person mới, không có Edge -> mọi field đều thiếu
        p = Person.objects.create(display_name="Không Edge")
        Document.objects.create(
            person=p, sha256="cv3", document_type="cv",
            parsed_text="Ngành: Khoa học dữ liệu. Số năm kinh nghiệm: 5.",
            parse_status=Document.PARSE_DONE)
        # cả hai đều là giá trị thẳng (model không bọc {value,...})
        run = run_for_person(
            p, use_ai=True,
            adapter=FakeAdapter('{"major": "Khoa học dữ liệu", "years_experience": "5"}'))
        self.assertEqual(run.status, run.STATUS_DONE)   # không nổ vì output lệch schema
        # years_experience (namespace rỗng, gate 0.70) -> conf mặc định 0.75 -> accepted
        self.assertEqual(current_facts(p, "years_experience").count(), 1)
        # major (gate 0.80) -> conf 0.75 chưa đủ -> vào review
        self.assertTrue(ExtractedFact.objects.filter(
            person=p, field="major", status=ExtractedFact.STATUS_PROPOSED).exists())

    def test_string_confidence_falls_back_safely(self):
        p = Person.objects.create(display_name="X")
        Document.objects.create(person=p, sha256="cvx", document_type="cv",
                                parsed_text="Số năm kinh nghiệm: 6 năm.",
                                parse_status=Document.PARSE_DONE)
        run = run_for_person(p, use_ai=True, adapter=FakeAdapter(
            '{"years_experience": {"value": "6", "confidence": "rất cao"}}'))
        self.assertEqual(run.status, run.STATUS_DONE)
        # confidence không parse được -> 0.5 -> dưới gate 0.70 -> review, không nổ
        self.assertTrue(ExtractedFact.objects.filter(
            person=p, field="years_experience",
            status=ExtractedFact.STATUS_PROPOSED).exists())

    def test_coverage_summary_reports_edge_reuse_ratio(self):
        runs = [run_for_person(self.person, use_ai=False)]
        summary = coverage_summary(runs)
        self.assertEqual(summary["runs"], 1)
        self.assertEqual(summary["runs_without_ai"], 1)
        self.assertIsNotNone(summary["edge_reuse_ratio"])
        self.assertEqual(summary["edge_reuse_ratio"], 1.0)   # 100% từ Edge, 0 AI


class HongImLangTest(TestCase):
    """Gọi AI, tốn token, không ra field nào — phải NHÌN THẤY được.

    Đo trên production 04/09/2026, ba CV thật: cả ba lượt chạy đóng lại ở trạng
    thái `done` với 0/14 field, mỗi lượt tốn ~1.500 token. Chuỗi thật:

        GreenNode timeout (prompt 12K ký tự)
          → router rơi sang gemini
            → gemini trả 30–129 token, JSON cụt giữa khoá
              → `_parse_json` nuốt lỗi, trả {}
                → coverage["ai"] = 0, status = done

    Ba tầng đều "hoạt động bình thường" theo cách nhìn của riêng nó, hợp lại
    thành một tính năng chạy tốn tiền mà không ra gì — và không ai đi tìm, vì
    không có gì đỏ. Đây là lời giải đầy đủ cho `industries` rỗng 0/786: kể cả 14
    lượt đã chạy cũng không thể ra field nào.
    """

    @classmethod
    def setUpTestData(cls):
        seeds.seed_all()

    def _nguoi_co_cv(self):
        person = Person.objects.create(display_name="Trần Thị Bình")
        Document.objects.create(
            person=person, sha256="cv-hong", document_type="cv",
            parsed_text="Tốt nghiệp Đại học Kinh tế. Ba năm làm kế toán tổng hợp.",
            parse_status=Document.PARSE_DONE)
        return person

    def test_json_cut_giua_chung_phai_hien_ra_o_coverage(self):
        cut = '{\n  "certifications": {\n    "value": [\n      "Bằng cử nhân"\n    ],\n    "evidence":'
        run = run_for_person(self._nguoi_co_cv(), use_ai=True,
                             adapter=FakeAdapter(cut))
        self.assertTrue(run.coverage.get("ai_parse_failed"),
                        "JSON hỏng mà coverage không mang dấu hiệu nào")
        self.assertEqual(run.coverage["ai_calls"], 1, "vẫn đã tốn một lượt gọi")

    def test_tra_ve_rong_hop_le_thi_danh_dau_khac_voi_json_hong(self):
        """`{}` hợp lệ nghĩa là 'CV không có gì' — khác hẳn 'model trả rác'.

        Gộp hai thứ này làm một là mất đúng thông tin cần để sửa: một bên phải
        đi chỉnh hạ tầng, một bên thì không.
        """
        run = run_for_person(self._nguoi_co_cv(), use_ai=True,
                             adapter=FakeAdapter("{}"))
        self.assertTrue(run.coverage.get("ai_empty"))
        self.assertFalse(run.coverage.get("ai_parse_failed"))

    def test_chay_binh_thuong_thi_khong_bat_co_nao(self):
        """Cờ báo động phải im khi mọi thứ ổn, nếu không nó thành nhiễu."""
        run = run_for_person(
            self._nguoi_co_cv(), use_ai=True,
            adapter=FakeAdapter('{"education_level": {"value": "Đại học", '
                                '"evidence": "Tốt nghiệp Đại học Kinh tế", '
                                '"confidence": 0.9}}'))
        self.assertFalse(run.coverage.get("ai_parse_failed"))
        self.assertFalse(run.coverage.get("ai_empty"))
        self.assertEqual(run.coverage.get("ai_model"), "fake-1",
                         "phải ghi model THẬT đã phục vụ — router có thể đã rơi "
                         "tầng sang nhà cung cấp khác với route đã cấu hình")
