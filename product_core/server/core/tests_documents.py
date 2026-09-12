# -*- coding: utf-8 -*-
"""Kiểm thử nhận file CV (phía Hub).

Yêu cầu nghiệp vụ: cùng một người ứng tuyển nhiều lần ở nhiều thời điểm sẽ nộp
nhiều file CV khác nhau — phải ghi nhận TẤT CẢ, xếp đúng thứ tự thời gian, và
không lưu trùng khi cùng một file đến từ hai nguồn.
"""
import hashlib
import json
import shutil
import tempfile
from types import SimpleNamespace

from django.test import TestCase, override_settings
from django.urls import reverse
from people import ingest
from people.models import Document, ParsedTextVersion, Person

from . import documents as documents_module
from .models import Edge, EdgeApiKey, SourceRecord
from .storage import reset_storage


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class DocumentIngestTest(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        reset_storage()
        self.addCleanup(reset_storage)
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        self.settings_patch = override_settings(
            FILE_STORAGE={"backend": "local", "root": self.folder})
        self.settings_patch.enable()
        self.addCleanup(self.settings_patch.disable)

    def _application(self, cv_id="1", applied="2026-08-01 09:00:00", **extra):
        payload = {"source": "topcv", "account": "ta@msb.com.vn", "cv_id": cv_id,
                   "fullname": "Nguyễn Văn An", "email": "an@example.com",
                   "phone": "0901234567", "applied_ts": applied}
        payload.update(extra)
        record = SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key=f"topcv|ta@msb.com.vn|{cv_id}", payload=payload,
            content_hash=f"h{cv_id}", source="topcv", fullname=payload["fullname"],
            email=payload["email"], phone=payload["phone"])
        ingest.resolve_pending()
        record.refresh_from_db()
        return record

    def _meta(self, digest, filename="cv.pdf", observed="2026-08-01 09:00:00", **extra):
        payload = {"sha256": digest, "filename": filename, "file_size": 100,
                   "mime_type": "application/pdf", "observed_at": observed,
                   "document_type": "cv", "source": "topcv"}
        payload.update(extra)
        return payload

    # ---------- nhiều phiên bản CV của cùng một người ----------

    def test_hai_lan_ung_tuyen_hai_file_khac_nhau_thanh_HAI_tai_lieu(self):
        """Yêu cầu cốt lõi: ghi nhận tất cả file CV của cùng một người."""
        old = self._application("1", applied="2023-03-01 09:00:00")
        new = self._application("2", applied="2026-08-01 09:00:00")

        documents_module.ingest_metadata(old, self._meta(
            _sha(b"CV nam 2023"), "cv_2023.pdf", "2023-03-01 09:00:00"))
        documents_module.ingest_metadata(new, self._meta(
            _sha(b"CV nam 2026"), "cv_2026.pdf", "2026-08-01 09:00:00"))

        person = Person.objects.get()
        self.assertEqual(person.documents.count(), 2)

        versions = documents_module.versions(person)
        self.assertEqual([d.filename for d in versions],
                         ["cv_2023.pdf", "cv_2026.pdf"], "cũ nhất trước")

    def test_so_thu_tu_phien_ban(self):
        a = self._application("1", applied="2023-03-01 09:00:00")
        b = self._application("2", applied="2026-08-01 09:00:00")
        documents_module.ingest_metadata(a, self._meta(_sha(b"v1"), "a.pdf",
                                                       "2023-03-01 09:00:00"))
        documents_module.ingest_metadata(b, self._meta(_sha(b"v2"), "b.pdf",
                                                       "2026-08-01 09:00:00"))
        versions = documents_module.versions(Person.objects.get())
        self.assertEqual([d.version_number() for d in versions], [1, 2])

    def test_CV_cu_dong_bo_MUON_van_nam_dung_cho(self):
        """Thứ tự theo ngày ứng tuyển, không theo lúc Hub nhận."""
        new = self._application("2", applied="2026-08-01 09:00:00")
        documents_module.ingest_metadata(new, self._meta(_sha(b"v2"), "moi.pdf",
                                                         "2026-08-01 09:00:00"))
        old = self._application("1", applied="2023-03-01 09:00:00")
        documents_module.ingest_metadata(old, self._meta(_sha(b"v1"), "cu.pdf",
                                                         "2023-03-01 09:00:00"))

        versions = documents_module.versions(Person.objects.get())
        self.assertEqual([d.filename for d in versions], ["cu.pdf", "moi.pdf"])

    def test_cung_mot_file_tu_hai_nguon_chi_la_MOT_tai_lieu(self):
        digest = _sha(b"cung mot CV")
        a = self._application("1")
        b = self._application("2")
        documents_module.ingest_metadata(a, self._meta(digest))
        documents_module.ingest_metadata(b, self._meta(digest))

        person = Person.objects.get()
        self.assertEqual(person.documents.count(), 1)
        # Nhưng vẫn biết nó được dùng cho HAI lượt ứng tuyển.
        self.assertEqual(person.documents.get().source_records.count(), 2)

    def test_giu_moc_thoi_gian_som_nhat(self):
        digest = _sha(b"cung mot CV")
        a = self._application("1", applied="2026-08-01 09:00:00")
        b = self._application("2", applied="2023-03-01 09:00:00")
        documents_module.ingest_metadata(a, self._meta(digest, observed="2026-08-01 09:00:00"))
        documents_module.ingest_metadata(b, self._meta(digest, observed="2023-03-01 09:00:00"))
        self.assertEqual(Document.objects.get().observed_at.year, 2023)

    def test_source_di_theo_moc_thoi_gian_som_nhat(self):
        """`source` và `observed_at` phải mô tả CÙNG một sự kiện.

        Không đồng bộ hai trường thì giao diện hiện "v2 · 20/6/2025 · careerviet"
        trong khi lượt ứng tuyển ngày đó lại ở VietnamWorks.
        """
        digest = _sha(b"cung mot CV")
        muon = self._application("1", applied="2026-08-01 09:00:00")
        som = self._application("2", applied="2025-06-20 09:00:00")

        documents_module.ingest_metadata(muon, self._meta(
            digest, "cv_careerviet.pdf", "2026-08-01 09:00:00", source="careerviet"))
        documents_module.ingest_metadata(som, self._meta(
            digest, "cv_vnw.pdf", "2025-06-20 09:00:00", source="vietnamworks"))

        document = Document.objects.get()
        self.assertEqual(document.observed_at.year, 2025)
        self.assertEqual(document.source, "vietnamworks")
        self.assertEqual(document.filename, "cv_vnw.pdf")

    def test_moc_muon_hon_khong_lam_doi_source(self):
        digest = _sha(b"cung mot CV")
        som = self._application("1", applied="2023-03-01 09:00:00")
        muon = self._application("2", applied="2026-08-01 09:00:00")
        documents_module.ingest_metadata(som, self._meta(
            digest, "cu.pdf", "2023-03-01 09:00:00", source="topcv"))
        documents_module.ingest_metadata(muon, self._meta(
            digest, "moi.pdf", "2026-08-01 09:00:00", source="careerviet"))

        document = Document.objects.get()
        self.assertEqual(document.source, "topcv")
        self.assertEqual(document.filename, "cu.pdf")

    # ---------- pha hai ----------

    def test_lan_dau_bao_can_file_lan_sau_thi_khong(self):
        record = self._application("1")
        content = b"noi dung CV"
        digest = _sha(content)

        _, needs_file = documents_module.ingest_metadata(record, self._meta(digest))
        self.assertTrue(needs_file)

        documents_module.store_file(record.person, digest, content)

        _, needs_file = documents_module.ingest_metadata(record, self._meta(digest))
        self.assertFalse(needs_file, "đã có file thì không đòi tải lại")

    def test_luu_file_va_doc_lai_duoc(self):
        record = self._application("1")
        content = b"noi dung CV that"
        documents_module.ingest_metadata(record, self._meta(_sha(content)))
        document = documents_module.store_file(record.person, _sha(content), content)
        self.assertTrue(document.storage_key)
        from .storage import get_storage
        self.assertEqual(get_storage().read(document.storage_key), content)

    def test_HUB_TU_BAM_LAI_khong_tin_Edge(self):
        """Edge lỗi không được ghi nội dung người này dưới mã băm người khác."""
        record = self._application("1")
        documents_module.ingest_metadata(record, self._meta(_sha(b"that")))
        with self.assertRaises(documents_module.DocumentError) as ctx:
            documents_module.store_file(record.person, _sha(b"that"), b"gia mao")
        self.assertIn("không khớp mã băm", str(ctx.exception))

    def test_chua_co_metadata_thi_khong_nhan_file(self):
        record = self._application("1")
        with self.assertRaises(documents_module.DocumentError):
            documents_module.store_file(record.person, _sha(b"x"), b"x")

    def test_file_qua_lon_bi_tu_choi(self):
        record = self._application("1")
        big = b"x" * (documents_module.MAX_FILE_BYTES + 1)
        documents_module.ingest_metadata(record, self._meta(_sha(big)))
        with self.assertRaises(documents_module.DocumentError):
            documents_module.store_file(record.person, _sha(big), big)

    def test_file_rong_bi_tu_choi(self):
        record = self._application("1")
        with self.assertRaises(documents_module.DocumentError):
            documents_module.store_file(record.person, _sha(b""), b"")

    # ---------- dữ liệu sai ----------

    def test_ma_bam_sai_bi_tu_choi(self):
        record = self._application("1")
        with self.assertRaises(documents_module.DocumentError):
            documents_module.ingest_metadata(record, self._meta("khong-phai-sha256"))

    def test_chua_phan_giai_Person_thi_bao_loi_tam_thoi(self):
        record = SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key="topcv|x|9", payload={"source": "topcv"}, content_hash="h9")
        with self.assertRaises(documents_module.DocumentError) as ctx:
            documents_module.ingest_metadata(record, self._meta(_sha(b"x")))
        self.assertIn("phân giải", str(ctx.exception))

    def test_text_dai_hon_thi_thay_the(self):
        """Edge có thể gửi text trước khi OCR xong rồi gửi lại bản đầy đủ hơn."""
        record = self._application("1")
        digest = _sha(b"x")
        documents_module.ingest_metadata(record, self._meta(digest, parsed_text="ngắn"))
        documents_module.ingest_metadata(
            record, self._meta(digest, parsed_text="dài hơn nhiều lắm"))
        document = Document.objects.select_related("primary_text_version").get()
        self.assertEqual(document.best_text, "dài hơn nhiều lắm")
        self.assertEqual(document.text_links.count(), 2)

    def test_text_ngan_hon_khong_ghi_de(self):
        record = self._application("1")
        digest = _sha(b"x")
        documents_module.ingest_metadata(
            record, self._meta(digest, parsed_text="đầy đủ và dài"))
        documents_module.ingest_metadata(record, self._meta(digest, parsed_text="ngắn"))
        document = Document.objects.select_related("primary_text_version").get()
        self.assertEqual(document.best_text, "đầy đủ và dài")
        self.assertEqual(document.text_links.count(), 2)

    def test_hai_file_khac_nhau_cung_text_chi_luu_mot_noi_dung(self):
        first = self._application("1")
        second = self._application("2")
        documents_module.ingest_metadata(
            first, self._meta(_sha(b"file-1"), parsed_text="Python\nSQL"))
        documents_module.ingest_metadata(
            second, self._meta(_sha(b"file-2"), parsed_text=" Python \r\n SQL "))
        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(ParsedTextVersion.objects.count(), 1)
        self.assertEqual(sum(d.text_links.count() for d in Document.objects.all()), 2)

    def test_hub_giu_ca_ban_trich_cuc_bo_va_ban_ai_khi_khac_nhau(self):
        from .cv_parsing import parse_missing_document

        record = self._application("1")
        content = "Kinh nghiệm Python và SQL".encode("utf-8")
        document, _ = documents_module.ingest_metadata(
            record, self._meta(_sha(content), filename="cv.txt", mime_type="text/plain"))
        documents_module.store_file(record.person, _sha(content), content, "cv.txt")

        def fake_complete(messages, **kwargs):
            self.assertIn("Kinh nghiệm Python", messages[1]["content"])
            return SimpleNamespace(text="Kinh nghiệm: Python, SQL", provider="fake", model="cv-1")

        parsed = parse_missing_document(document, complete_fn=fake_complete)
        self.assertEqual(parsed.parse_status, Document.PARSE_DONE)
        self.assertEqual(parsed.text_links.count(), 2)
        self.assertEqual(parsed.parse_provider, "fake")

    def test_ban_trich_da_sach_thi_khong_goi_ai(self):
        """Đo được: trên CV sạch, LLM trả lại 3.130/3.135 ký tự và giữ y nguyên
        mọi năm/email/số. Tức nó sửa gần như KHÔNG GÌ, đổi lấy ~30 giây và một
        lượt gọi cho mỗi hồ sơ nhập vào. Đó là gọi cho có."""
        from .cv_parsing import parse_missing_document

        record = self._application("sach")
        sach = ("NGUYỄN VĂN AN\nEmail: an.nguyen@example.com\nĐiện thoại: 0912345678\n\n"
                "KINH NGHIỆM LÀM VIỆC\n"
                "2021 - 2024: Kỹ sư phần mềm tại Công ty Cổ phần Công nghệ ABC\n"
                "Phát triển hệ thống bằng Python, Django và PostgreSQL.\n"
                "2019 - 2021: Lập trình viên tại Công ty TNHH XYZ\n"
                "Xây dựng giao diện web bằng React và TypeScript.\n\n"
                "HỌC VẤN\n2015 - 2019: Đại học Bách khoa Hà Nội, ngành Công nghệ thông tin.\n"
                "KỸ NĂNG\nPython, JavaScript, SQL, Docker, tiếng Anh giao tiếp tốt.\n")
        content = sach.encode("utf-8")
        document, _ = documents_module.ingest_metadata(
            record, self._meta(_sha(content), filename="cv.txt", mime_type="text/plain"))
        documents_module.store_file(record.person, _sha(content), content, "cv.txt")

        def khong_duoc_goi(messages, **kwargs):
            self.fail("Đã gọi AI dù bản trích cục bộ sạch.")

        parsed = parse_missing_document(document, complete_fn=khong_duoc_goi)
        self.assertEqual(parsed.parse_status, Document.PARSE_DONE)
        self.assertIn("an.nguyen@example.com", parsed.best_text)
        # Chỉ còn MỘT bản: bản trích cục bộ. Không có bản AI vì không gọi AI.
        self.assertEqual(parsed.text_links.count(), 1)

    def test_ban_trich_xau_thi_van_goi_ai(self):
        """Bỏ qua phải có điều kiện, không phải tắt hẳn — nếu không thì lại
        thành bỏ sót đúng những hồ sơ cần cứu nhất."""
        from .cv_parsing import can_ai_chuan_hoa

        dem = " ".join(["chu"] * 90)          # đủ dài để qua ngưỡng 200 ký tự
        for text, vi_sao in [
            ("ngắn quá", "dưới 200 ký tự"),
            ("NguyễnVănAn" * 40, "chữ dính nhau, thiếu khoảng trắng"),
            ("A" + "█▓▒░" * 90 + " b c d e f g h i j k l m n", "rác ký tự"),
            ("KinhNghiemLamViecTaiCongTyCoPhanCongNgheABCVaXYZTuNamHaiNghinKhongTramHaiMuoi "
             + dem, "cả dòng chữ dính thành một khối"),
        ]:
            with self.subTest(vi_sao=vi_sao):
                can, ly_do = can_ai_chuan_hoa(text)
                self.assertTrue(can, f"{vi_sao}: đáng lẽ phải gọi AI")
                self.assertTrue(ly_do, "phải nói lý do để còn chỉnh ngưỡng")

    def test_khong_bao_dong_gia_voi_url_va_dau_trang_tri(self):
        """Đo trên 420 CV thật: bản đầu đo 'từ dài' và một nửa số ca nó bắt là
        báo động giả — URL LinkedIn/Facebook, dấu chấm kẻ dòng, gạch chân tiêu
        đề. Gọi LLM 31 giây để xoá dấu chấm cũng là gọi cho có."""
        from .cv_parsing import can_ai_chuan_hoa

        than = ("\nKinh nghiem lam viec tai cong ty cong nghe. Phat trien he thong "
                "bang Python va Django. Hoc dai hoc Bach khoa Ha Noi nganh cong nghe "
                "thong tin. Ky nang: SQL, Docker, tieng Anh giao tiep tot.\n") * 2
        for text, vi_sao in [
            ("https://www.linkedin.com/in/nguyen-duc-anh-3020a0251/" + than, "URL LinkedIn 54 ký tự"),
            ("https://www.facebook.com/billvova2005?locale=vi_VN" + than, "URL Facebook 50 ký tự"),
            ("Muc luc " + "." * 141 + than, "dấu chấm kẻ dòng 141 ký tự"),
            ("Expertise" + "_" * 100 + than, "gạch chân kẻ tiêu đề"),
        ]:
            with self.subTest(vi_sao=vi_sao):
                can, ly_do = can_ai_chuan_hoa(text)
                self.assertFalse(can, f"{vi_sao}: báo động giả — {ly_do}")

    def test_pdf_scan_duoc_ocr_bang_ai_vision(self):
        from .cv_parsing import parse_missing_document
        import fitz

        record = self._application("scan")
        pdf = fitz.open()
        page = pdf.new_page()
        page.draw_rect(fitz.Rect(20, 20, 200, 100), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
        data = pdf.tobytes()
        pdf.close()
        document, _ = documents_module.ingest_metadata(record, self._meta(_sha(data), filename="scan.pdf"))
        documents_module.store_file(record.person, _sha(data), data, "scan.pdf")

        def fake_complete(messages, **kwargs):
            self.assertEqual(kwargs["task"], "cv_ocr")
            self.assertIsInstance(messages[1]["content"], list)
            self.assertEqual(messages[1]["content"][1]["type"], "image_url")
            return SimpleNamespace(text="Nguyễn Văn An\nKinh nghiệm Python", provider="vision", model="vision-1")

        parsed = parse_missing_document(document, complete_fn=fake_complete)
        self.assertEqual(parsed.best_text, "Nguyễn Văn An\nKinh nghiệm Python")
        self.assertEqual(parsed.parse_provider, "vision")


class DocumentApiTest(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        reset_storage()
        self.addCleanup(reset_storage)
        self.settings_patch = override_settings(
            FILE_STORAGE={"backend": "local", "root": self.folder})
        self.settings_patch.enable()
        self.addCleanup(self.settings_patch.disable)

        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        _, self.key = EdgeApiKey.issue(self.edge)

    def _push(self, records):
        return self.client.post(
            reverse("edge-sync"),
            data=json.dumps({"edge_id": "e1", "records": records}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.key}")

    def _application_record(self, cv_id="1"):
        return {"entity_type": "source_record",
                "entity_key": f"topcv|ta@msb.com.vn|{cv_id}",
                "source": "topcv", "account": "ta@msb.com.vn", "cv_id": cv_id,
                "fullname": "Nguyễn Văn An", "email": "an@example.com",
                "phone": "0901234567", "applied_ts": "2026-08-01 09:00:00"}

    def _document_record(self, cv_id="1", digest=None):
        return {"entity_type": "document",
                "entity_key": f"topcv|ta@msb.com.vn|{cv_id}",
                "sha256": digest or _sha(b"noi dung"), "filename": "cv.pdf",
                "file_size": 8, "mime_type": "application/pdf",
                "observed_at": "2026-08-01 09:00:00"}

    def test_ket_qua_co_entity_type_de_khong_cham_nhau(self):
        """Tài liệu và lượt ứng tuyển dùng chung entity_key."""
        response = self._push([self._application_record(),
                               self._document_record()])
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        kinds = {r["entity_type"] for r in results}
        self.assertEqual(kinds, {"source_record", "document"})

    def test_tai_lieu_duoc_xu_ly_SAU_ban_ghi_nguon_trong_cung_lo(self):
        """Tài liệu cần một Person để gắn vào, nên thứ tự trong lô không quan trọng."""
        response = self._push([self._document_record(), self._application_record()])
        doc_result = [r for r in response.json()["results"]
                      if r["entity_type"] == "document"][0]
        self.assertEqual(doc_result["status"], "accepted")
        self.assertTrue(doc_result["needs_file"])

    def test_chua_co_ban_ghi_nguon_thi_bao_thu_lai(self):
        response = self._push([self._document_record("99")])
        result = response.json()["results"][0]
        self.assertEqual(result["status"], "retry")

    def test_tai_file_len_va_doc_lai(self):
        content = b"noi dung"
        digest = _sha(content)
        self._push([self._application_record(), self._document_record(digest=digest)])

        response = self.client.post(
            reverse("edge-document-upload", args=[digest])
            + "?entity_key=topcv|ta@msb.com.vn|1&filename=cv.pdf",
            data=content, content_type="application/octet-stream",
            HTTP_AUTHORIZATION=f"Bearer {self.key}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["storage_key"])
        self.assertTrue(Document.objects.get().has_file)

    def test_tai_len_noi_dung_khong_khop_ma_bam_bi_tu_choi(self):
        digest = _sha(b"that")
        self._push([self._application_record(), self._document_record(digest=digest)])
        response = self.client.post(
            reverse("edge-document-upload", args=[digest])
            + "?entity_key=topcv|ta@msb.com.vn|1",
            data=b"gia mao", content_type="application/octet-stream",
            HTTP_AUTHORIZATION=f"Bearer {self.key}")
        self.assertEqual(response.status_code, 400)

    def test_tai_len_khong_xac_thuc_bi_chan(self):
        response = self.client.post(
            reverse("edge-document-upload", args=["a" * 64]) + "?entity_key=x",
            data=b"x", content_type="application/octet-stream")
        self.assertEqual(response.status_code, 401)
