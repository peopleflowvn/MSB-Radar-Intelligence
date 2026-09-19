# -*- coding: utf-8 -*-
"""Kiểm thử đảm bảo MỌI CV có file đều có text dùng được để tìm kiếm.

Bối cảnh (prod 20/09): 12/611 CV có file nhưng không tìm được — trang bìa TopCV
82 ký tự của PDF ảnh nằm ở trạng thái `done`, OCR trả câu "không có chữ" và câu
đó được lưu làm nội dung CV, file Excel/gói ảnh mang đuôi .docx, Word hỏng CRC
một ảnh. Worker cũ chỉ bắt "chưa có text nào" và lặp lại mãi 3 file hỏng.
"""
import hashlib
import io
import shutil
import tempfile
import zipfile
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from people import ingest
from people.models import Document
from people.parsed_text import is_usable_text, looks_like_ocr_empty

from . import cv_parsing
from . import documents as documents_module
from .models import Edge, SourceRecord
from .storage import reset_storage

CV_THAT = ("NGUYỄN VĂN AN\nChuyên viên quan hệ khách hàng doanh nghiệp\n"
           "KINH NGHIỆM LÀM VIỆC\n2021 - 2024: Ngân hàng TMCP ABC, phụ trách danh mục "
           "khách hàng doanh nghiệp vừa và nhỏ, thẩm định tín dụng, bán chéo sản phẩm.\n"
           "2019 - 2021: Chuyên viên tín dụng tại Công ty Tài chính XYZ.\n"
           "HỌC VẤN\nĐại học Kinh tế Quốc dân, ngành Tài chính Ngân hàng.\n"
           "KỸ NĂNG\nPhân tích báo cáo tài chính, thẩm định dự án, tiếng Anh giao tiếp.\n"
           "MỤC TIÊU\nPhát triển thành quản lý quan hệ khách hàng doanh nghiệp, xây dựng "
           "danh mục bền vững và đóng góp vào tăng trưởng tín dụng của ngân hàng.\n")
TRANG_BIA = "Ứng viên: Lê Quý Thịnh | Nguồn: tuyendung.topcv.vn AID: Bwg5aGxcWXhWZgd9B2Zf"
OCR_RONG = ("Không có nội dung văn bản nào trong hình ảnh được cung cấp. Hình ảnh hoàn "
            "toàn trắng, không chứa chữ, logo, hoặc bất kỳ thông tin nào.")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _png(size=(40, 40)):
    from PIL import Image
    output = io.BytesIO()
    Image.new("RGB", size, (250, 250, 250)).save(output, format="PNG")
    return output.getvalue()


def _big_png():
    """Ảnh đủ lớn để không bị coi là logo (> 8 KB) — nhiễu nên nén không nhỏ."""
    import random
    from PIL import Image
    rng = random.Random(1)
    image = Image.new("RGB", (160, 160))
    image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                   for _ in range(160 * 160)])
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _zip(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return output.getvalue()


def _docx_xml(text):
    paragraphs = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>"
                         for line in text.splitlines())
    return ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w='
            '"http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{paragraphs}</w:body></w:document>").encode("utf-8")


def _image_pdf():
    import fitz
    pdf = fitz.open()
    page = pdf.new_page()
    page.draw_rect(fitz.Rect(20, 20, 200, 100), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
    data = pdf.tobytes()
    pdf.close()
    return data


class _Base(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        reset_storage()
        self.addCleanup(reset_storage)
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        patcher = override_settings(FILE_STORAGE={"backend": "local", "root": self.folder})
        patcher.enable()
        self.addCleanup(patcher.disable)
        self.calls = []

    def _document(self, data, filename, parsed_text="", key="1"):
        record = SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key=f"topcv|ta|{key}", content_hash=f"h{key}", source="topcv",
            payload={"source": "topcv", "cv_id": key, "fullname": f"Người {key}",
                     "email": f"u{key}@example.com", "phone": f"09012345{int(key):02d}"},
            fullname=f"Người {key}", email=f"u{key}@example.com",
            phone=f"09012345{int(key):02d}")
        ingest.resolve_pending()
        record.refresh_from_db()
        meta = {"sha256": _sha(data), "filename": filename, "file_size": len(data),
                "mime_type": "application/octet-stream", "observed_at": "2026-08-01 09:00:00",
                "document_type": "cv", "source": "topcv"}
        if parsed_text:
            meta["parsed_text"] = parsed_text
        document, _ = documents_module.ingest_metadata(record, meta)
        documents_module.store_file(record.person, _sha(data), data, filename)
        return Document.objects.get(pk=document.pk)

    def _ocr(self, text):
        def fake(messages, **kwargs):
            self.calls.append(kwargs.get("task"))
            return SimpleNamespace(text=text, provider="vision", model="vision-1")
        return fake

    def _reload(self, document):
        return Document.objects.select_related("primary_text_version").get(pk=document.pk)


class ChatLuongTextTest(TestCase):
    def test_trang_bia_topcv_va_cau_ocr_rong_khong_dung_duoc(self):
        self.assertFalse(is_usable_text(TRANG_BIA))
        self.assertFalse(is_usable_text(OCR_RONG))
        self.assertTrue(looks_like_ocr_empty(OCR_RONG))
        self.assertTrue(is_usable_text(CV_THAT))
        self.assertFalse(looks_like_ocr_empty(CV_THAT))

    def test_cv_that_nhac_toi_hinh_anh_khong_bi_coi_la_ocr_rong(self):
        """CV thiết kế đồ hoạ viết "xử lý hình ảnh" không phải câu từ chối."""
        text = CV_THAT + "Kỹ năng: xử lý hình ảnh, thiết kế văn bản quảng cáo."
        self.assertFalse(looks_like_ocr_empty(text))


class ParseBuTest(_Base):
    def test_trang_bia_edge_gui_len_duoc_ocr_lai_va_thay_the(self):
        """Edge gửi trang bìa 82 ký tự cho PDF ảnh, trạng thái `done`. Worker cũ
        bỏ qua vì "đã có text" — CV đó không bao giờ tìm được."""
        document = self._document(_image_pdf(), "cv.pdf", parsed_text=TRANG_BIA)
        self.assertEqual(document.parse_status, Document.PARSE_DONE)
        self.assertIn(document, cv_parsing.due_for_parsing())

        handled = cv_parsing.parse_due_documents(10, complete_fn=self._ocr(CV_THAT))

        document = self._reload(document)
        self.assertEqual(handled, 1)
        self.assertEqual(self.calls, ["cv_ocr"])
        self.assertIn("quan hệ khách hàng doanh nghiệp", document.best_text)
        self.assertNotIn(document, cv_parsing.needs_parsing(), "xong thì rời hàng đợi")

    def test_ocr_bao_trang_trang_thi_chot_unreadable_va_khong_luu_cau_do(self):
        document = self._document(_image_pdf(), "trang.pdf")
        cv_parsing.parse_due_documents(10, complete_fn=self._ocr(OCR_RONG))

        document = self._reload(document)
        self.assertEqual(document.parse_status, Document.PARSE_UNREADABLE)
        self.assertEqual(document.best_text, "")
        # Đọc lại ở độ phân giải cao hơn MỘT lần trước khi kết luận.
        self.assertEqual(self.calls, ["cv_ocr", "cv_ocr"])
        self.assertNotIn(document, cv_parsing.needs_parsing(), "không gọi OCR mãi")

    def test_cau_ocr_rong_da_lo_luu_thi_duoc_go_khoi_noi_dung(self):
        document = self._document(_image_pdf(), "trang.pdf")
        # Bản cũ trước sửa: câu đó đã nằm làm nội dung CV.
        from people.models import ParsedTextVersion
        version = ParsedTextVersion.objects.create(
            person_id=document.person_id, text_hash="x" * 64, text=OCR_RONG,
            text_length=len(OCR_RONG))
        Document.objects.filter(pk=document.pk).update(
            primary_text_version=version, text_length=len(OCR_RONG), parse_status="done")

        cv_parsing.parse_due_documents(10, complete_fn=self._ocr(OCR_RONG))
        document = self._reload(document)
        self.assertIsNone(document.primary_text_version_id)
        self.assertEqual(document.parse_status, Document.PARSE_UNREADABLE)

    def test_excel_mang_duoi_docx_van_doc_duoc(self):
        from openpyxl import Workbook
        workbook = Workbook()
        for line in CV_THAT.splitlines():
            workbook.active.append([line])
        output = io.BytesIO()
        workbook.save(output)

        document = self._document(output.getvalue(), "cv.docx")
        cv_parsing.parse_due_documents(10, complete_fn=self._ocr("không được gọi"))

        document = self._reload(document)
        self.assertIn("Kinh tế Quốc dân", document.best_text)
        self.assertEqual(self.calls, [], "trích cục bộ đủ tốt thì không cần AI")

    def test_word_hong_mot_anh_van_lay_duoc_chu(self):
        data = _zip({"[Content_Types].xml": b"<Types/>",
                     "word/document.xml": _docx_xml(CV_THAT),
                     "word/media/image1.jpeg": b"khong phai anh"})
        document = self._document(data, "cv.docx")
        with patch("talent.attachment_text._extract",
                   side_effect=zipfile.BadZipFile("Bad CRC-32 for file 'word/media/image9.jpeg'")):
            cv_parsing.parse_due_documents(10, complete_fn=self._ocr("không được gọi"))
        self.assertIn("Kinh tế Quốc dân", self._reload(document).best_text)

    def test_goi_anh_chup_mang_duoi_docx_duoc_ocr_tung_trang(self):
        data = _zip({"trang_0.jpeg": _png(), "trang_1.jpeg": _png(), "trang_2.jpeg": _png()})
        document = self._document(data, "cv.docx")
        pages = []

        def fake(messages, **kwargs):
            pages.append(sum(1 for part in messages[1]["content"]
                             if part["type"] == "image_url"))
            return SimpleNamespace(text=CV_THAT, provider="vision", model="vision-1")

        cv_parsing.parse_due_documents(10, complete_fn=fake)
        self.assertEqual(pages, [3])
        self.assertIn("Kinh tế Quốc dân", self._reload(document).best_text)

    def test_word_chi_chua_anh_cv_duoc_ocr_anh_nhung(self):
        data = _zip({"[Content_Types].xml": b"<Types/>",
                     "word/document.xml": _docx_xml("Nguyễn Văn An"),
                     "word/media/logo.png": _png((8, 8)),
                     "word/media/image1.png": _big_png()})
        document = self._document(data, "cv.docx")
        pages = []

        def fake(messages, **kwargs):
            pages.append(sum(1 for part in messages[1]["content"]
                             if part["type"] == "image_url"))
            return SimpleNamespace(text=CV_THAT, provider="vision", model="vision-1")

        cv_parsing.parse_due_documents(10, complete_fn=fake)
        self.assertEqual(pages, [1], "logo nhỏ bị bỏ, chỉ OCR ảnh CV")
        self.assertIn("Kinh tế Quốc dân", self._reload(document).best_text)

    def test_file_nhi_phan_la_duoc_ai_dung_lai_tu_chuoi_chu(self):
        """.doc Word 97–2003: không có thư viện đọc, không có ảnh để OCR."""
        body = CV_THAT.encode("utf-16-le")
        data = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00\x01\xff" * 200 + body + b"\x02" * 300
        document = self._document(data, "cv.doc")
        seen = []

        def fake(messages, **kwargs):
            seen.append((kwargs["task"], messages[1]["content"]))
            return SimpleNamespace(text=CV_THAT, provider="llm", model="llm-1")

        cv_parsing.parse_due_documents(10, complete_fn=fake)
        self.assertEqual(seen[0][0], "cv_parsing")
        self.assertIn("Kinh tế Quốc dân", seen[0][1])
        self.assertIn("Kinh tế Quốc dân", self._reload(document).best_text)

    def test_text_moi_thi_xep_hang_boc_fact_lai(self):
        from intel.models import ExtractionJob
        document = self._document(_image_pdf(), "cv.pdf", parsed_text=TRANG_BIA)
        ExtractionJob.objects.all().delete()
        cv_parsing.parse_due_documents(10, complete_fn=self._ocr(CV_THAT))
        self.assertTrue(ExtractionJob.objects.filter(person_id=document.person_id).exists())


class ThuLaiTest(_Base):
    def _loi(self, *args, **kwargs):
        self.calls.append("x")
        raise TimeoutError("The read operation timed out")

    def test_loi_thi_hen_lai_khong_lap_ngay(self):
        """Worker cũ chọn lại đúng 3 file hỏng mỗi 3 giây, mãi mãi."""
        document = self._document(_image_pdf(), "cv.pdf")
        cv_parsing.parse_due_documents(10, complete_fn=self._loi)
        cv_parsing.parse_due_documents(10, complete_fn=self._loi)

        document = self._reload(document)
        self.assertEqual(len(self.calls), 1, "chưa tới hạn thì không thử lại")
        self.assertEqual(document.parse_status, Document.PARSE_FAILED)
        self.assertGreater(document.next_parse_at, timezone.now())
        self.assertIn(document, cv_parsing.needs_parsing(), "vẫn trong hàng đợi")

        Document.objects.filter(pk=document.pk).update(
            next_parse_at=timezone.now() - timedelta(seconds=1))
        cv_parsing.parse_due_documents(10, complete_fn=self._ocr(CV_THAT))
        self.assertIn("Kinh tế Quốc dân", self._reload(document).best_text)

    def test_het_luot_thi_chot_unreadable(self):
        document = self._document(_image_pdf(), "cv.pdf")
        for _ in range(len(cv_parsing.RETRY_BACKOFF) + 1):
            Document.objects.filter(pk=document.pk).update(next_parse_at=None)
            cv_parsing.parse_due_documents(10, complete_fn=self._loi)
        document = self._reload(document)
        self.assertEqual(document.parse_status, Document.PARSE_UNREADABLE)
        self.assertNotIn(document, cv_parsing.needs_parsing())

    def test_het_luot_chuan_hoa_nhung_text_da_tot_thi_khong_gan_unreadable(self):
        document = self._document(b"%PDF-1.4 x", "cv.pdf", parsed_text=CV_THAT)
        Document.objects.filter(pk=document.pk).update(
            parse_provider="hub", parse_error="timeout",
            parse_attempts=len(cv_parsing.RETRY_BACKOFF), next_parse_at=timezone.now())
        cv_parsing.parse_due_documents(10, complete_fn=self._loi)
        document = self._reload(document)
        self.assertEqual(document.parse_status, Document.PARSE_DONE)
        self.assertIsNone(document.next_parse_at)
        self.assertNotIn(document, cv_parsing.needs_parsing())

    def test_hai_tien_trinh_khong_xu_ly_cung_mot_file(self):
        """Hub chạy worker trong cả 3 tiến trình gunicorn."""
        document = self._document(_image_pdf(), "cv.pdf")
        self.assertTrue(cv_parsing.claim(document))
        self.assertFalse(cv_parsing.claim(document))
        self.assertEqual(cv_parsing.parse_due_documents(10, complete_fn=self._loi), 0)

    def test_cv_ngan_that_su_duoc_kiem_mot_lan_roi_thoi(self):
        """CV thật ngắn (< 1500 ký tự) được kiểm một lần; text tốt thì không
        gọi AI và không bị chọn lại."""
        document = self._document(b"%PDF-1.4 x", "cv.pdf", parsed_text=CV_THAT)
        self.assertIn(document, cv_parsing.due_for_parsing())
        cv_parsing.parse_due_documents(10, complete_fn=self._ocr("không được gọi"))
        self.assertEqual(self.calls, [])
        self.assertNotIn(self._reload(document), cv_parsing.needs_parsing())

    def test_retry_failed_mo_lai_file_unreadable(self):
        from django.core.management import call_command
        document = self._document(_image_pdf(), "trang.pdf")
        cv_parsing.parse_due_documents(10, complete_fn=self._ocr(OCR_RONG))
        self.assertEqual(self._reload(document).parse_status, Document.PARSE_UNREADABLE)
        with patch("core.cv_parsing.complete", self._ocr(CV_THAT)):
            call_command("parse_missing_cvs", "--retry-failed", stdout=io.StringIO())
        self.assertIn("Kinh tế Quốc dân", self._reload(document).best_text)


class WorkerTest(_Base):
    def test_worker_dung_hang_doi_moi(self):
        from . import worker
        document = self._document(_image_pdf(), "cv.pdf", parsed_text=TRANG_BIA)
        with patch("core.cv_parsing.complete", self._ocr(CV_THAT)), \
                patch("core.document_preview.prepare_preview"):
            worker._parse_documents()
        self.assertIn("Kinh tế Quốc dân", self._reload(document).best_text)
