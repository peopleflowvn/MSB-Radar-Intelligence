# -*- coding: utf-8 -*-
"""Kiểm thử đồng bộ file CV (phía Edge).

Bối cảnh: cùng một người ứng tuyển nhiều lần ở nhiều thời điểm sẽ nộp nhiều file
CV khác nhau. Phải ghi nhận TẤT CẢ, và phải không gửi lại những file đã có.
"""
import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import Database
from app.sync import runner
from app.sync.payload import (ENTITY_DOCUMENT, ENTITY_SOURCE_RECORD,
                              document_payload, payload_hash)


class DocumentPayloadTest(unittest.TestCase):
    def test_dung_chung_entity_key_voi_luot_ung_tuyen(self):
        """Nhờ vậy Hub tìm được bản ghi nguồn, và qua đó là Person."""
        row = {"source": "topcv", "account": "ta@msb.com.vn", "cv_id": "9",
               "sha256": "a" * 64}
        self.assertEqual(document_payload(row)["entity_key"], "topcv|ta@msb.com.vn|9")
        self.assertEqual(document_payload(row)["entity_type"], ENTITY_DOCUMENT)

    def test_KHONG_gui_kem_noi_dung_file(self):
        """Nội dung đi ở pha hai; kho CV ~4 GB không được nằm trong mỗi lô."""
        payload = document_payload({"source": "topcv", "cv_id": "1",
                                    "sha256": "a" * 64, "filename": "cv.pdf"})
        for key in payload:
            self.assertNotIn("content", key)
            self.assertNotIn("base64", key)

    def test_doan_mime_tu_duoi_file(self):
        payload = document_payload({"source": "topcv", "cv_id": "1",
                                    "sha256": "a" * 64, "filename": "ho so.PDF"})
        self.assertEqual(payload["mime_type"], "application/pdf")

    def test_gui_kem_text_da_boc_tach(self):
        payload = document_payload({"source": "topcv", "cv_id": "1", "sha256": "a" * 64,
                                    "full_text": "Nguyễn Văn An — Data Analyst"})
        self.assertIn("Data Analyst", payload["parsed_text"])

    def test_hash_doi_khi_file_doi(self):
        base = {"source": "topcv", "cv_id": "1", "filename": "cv.pdf"}
        a = payload_hash(document_payload(dict(base, sha256="a" * 64)))
        b = payload_hash(document_payload(dict(base, sha256="b" * 64)))
        self.assertNotEqual(a, b)


class ScanDocumentsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.cv_folder = os.path.join(self.folder, "CV")
        os.makedirs(self.cv_folder)
        self.db = Database(os.path.join(self.folder, "test.db"),
                           log=lambda *a: None).open()
        self.addCleanup(self.db.close)

    def _candidate(self, cv_id="1", filename="cv1.pdf", applied="2026-08-01 09:00:00"):
        self.db.upsert({"source": "topcv", "account": "ta@msb.com.vn", "cv_id": cv_id,
                        "fullname": "Nguyễn Văn An", "email": "an@example.com",
                        "phone": "0901234567", "applied_ts": applied,
                        "filename": filename, "dl_status": "done"})
        self.db.commit()

    def _file(self, name, content=b"noi dung CV"):
        path = os.path.join(self.cv_folder, name)
        with open(path, "wb") as handle:
            handle.write(content)
        return hashlib.sha256(content).hexdigest()

    def _document_row(self, cv_id, filename, digest):
        now = "2026-08-01 09:00:00"
        self.db._write(
            """INSERT INTO candidate_documents
                 (source,account,cv_id,filename,file_hash,file_size,file_format,
                  parse_status,full_text,text_length,queued_at,updated_at)
               VALUES ('topcv','ta@msb.com.vn',?,?,?,100,'pdf','done','text',4,?,?)""",
            (cv_id, filename, digest, now, now))
        self.db.commit()

    def test_xep_hang_tai_lieu_co_file_tren_dia(self):
        self._candidate("1", "cv1.pdf")
        digest = self._file("cv1.pdf")
        self._document_row("1", "cv1.pdf", digest)

        self.assertEqual(runner.scan_documents(self.db, self.cv_folder)[0], 1)
        self.assertEqual(self.db.sync_stats()["pending"], 1)

    def test_bo_qua_khi_file_khong_con_tren_dia(self):
        """CSDL còn hàng nhưng file đã bị dọn — xếp hàng chỉ tạo việc thất bại."""
        self._candidate("1", "mat-roi.pdf")
        self._document_row("1", "mat-roi.pdf", "a" * 64)
        self.assertEqual(runner.scan_documents(self.db, self.cv_folder)[0], 0)

    def test_bo_qua_khi_chua_co_ma_bam(self):
        """Không có sha256 thì Hub không khử trùng lặp theo nội dung được."""
        self._candidate("1", "cv1.pdf")
        self._file("cv1.pdf")
        self._document_row("1", "cv1.pdf", "")
        self.assertEqual(runner.scan_documents(self.db, self.cv_folder)[0], 0)

    def test_quet_lai_khong_sinh_viec_moi(self):
        self._candidate("1", "cv1.pdf")
        digest = self._file("cv1.pdf")
        self._document_row("1", "cv1.pdf", digest)
        runner.scan_documents(self.db, self.cv_folder)
        self.assertEqual(runner.scan_documents(self.db, self.cv_folder)[0], 0)

    def test_chan_thoat_thu_muc(self):
        """filename đến từ dữ liệu nhà cung cấp; không được trỏ ra ngoài thư mục CV."""
        for bad in ("../ngoai.pdf", "..\\..\\windows\\win.ini", "sub/../../x.pdf"):
            self.assertEqual(runner._document_path(self.cv_folder, bad), "")

    def test_nhieu_luot_ung_tuyen_cho_nhieu_tai_lieu(self):
        """Đây chính là ca cần: một người, nhiều lượt, nhiều file CV khác nhau."""
        self._candidate("1", "cv_2023.pdf", "2023-03-01 09:00:00")
        self._candidate("2", "cv_2026.pdf", "2026-08-01 09:00:00")
        d1 = self._file("cv_2023.pdf", b"CV nam 2023")
        d2 = self._file("cv_2026.pdf", b"CV nam 2026 da cap nhat")
        self._document_row("1", "cv_2023.pdf", d1)
        self._document_row("2", "cv_2026.pdf", d2)

        self.assertEqual(runner.scan_documents(self.db, self.cv_folder)[0], 2)
        self.assertNotEqual(d1, d2, "hai file khác nội dung phải khác mã băm")


class _Hub:
    """Hub giả có theo dõi cả pha hai."""

    def __init__(self, has_files=()):
        self.has_files = set(has_files)
        self.uploads = []

    def push_batch(self, records):
        results = {}
        for record in records:
            kind = record.get("entity_type") or ENTITY_SOURCE_RECORD
            answer = {"entity_key": record["entity_key"], "entity_type": kind,
                      "status": "accepted", "id": "h1"}
            if kind == ENTITY_DOCUMENT:
                answer["sha256"] = record.get("sha256", "")
                answer["needs_file"] = record.get("sha256") not in self.has_files
            results[(kind, record["entity_key"])] = answer
        return results

    def upload_document(self, sha256, entity_key, data, filename=""):
        self.uploads.append({"sha256": sha256, "entity_key": entity_key,
                             "size": len(data), "filename": filename})
        self.has_files.add(sha256)
        return {"ok": True}


class UploadPhaseTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.cv_folder = os.path.join(self.folder, "CV")
        os.makedirs(self.cv_folder)
        self.db = Database(os.path.join(self.folder, "test.db"),
                           log=lambda *a: None).open()
        self.addCleanup(self.db.close)

        self.content = b"day la noi dung CV that"
        self.digest = hashlib.sha256(self.content).hexdigest()
        with open(os.path.join(self.cv_folder, "cv1.pdf"), "wb") as handle:
            handle.write(self.content)

        self.db.upsert({"source": "topcv", "account": "ta@msb.com.vn", "cv_id": "1",
                        "fullname": "Nguyễn Văn An", "email": "an@example.com",
                        "phone": "0901234567", "applied_ts": "2026-08-01 09:00:00",
                        "filename": "cv1.pdf", "dl_status": "done"})
        now = "2026-08-01 09:00:00"
        self.db._write(
            """INSERT INTO candidate_documents
                 (source,account,cv_id,filename,file_hash,file_size,file_format,
                  parse_status,full_text,text_length,queued_at,updated_at)
               VALUES ('topcv','ta@msb.com.vn','1','cv1.pdf',?,23,'pdf','done','t',1,?,?)""",
            (self.digest, now, now))
        self.db.commit()
        runner.scan_documents(self.db, self.cv_folder)

    def test_tai_len_khi_hub_bao_chua_co(self):
        hub = _Hub()
        outcome = runner.push_once(self.db, hub, "e1", log=lambda *a: None,
                                   cv_folder=self.cv_folder)
        self.assertEqual(outcome["uploaded"], 1)
        self.assertEqual(hub.uploads[0]["sha256"], self.digest)
        self.assertEqual(hub.uploads[0]["size"], len(self.content))

    def test_KHONG_tai_len_khi_hub_da_co(self):
        """Đây là thứ giúp không phải đẩy lại ~4 GB mỗi lần quét."""
        hub = _Hub(has_files=[self.digest])
        outcome = runner.push_once(self.db, hub, "e1", log=lambda *a: None,
                                   cv_folder=self.cv_folder)
        self.assertEqual(outcome["uploaded"], 0)
        self.assertEqual(hub.uploads, [])
        self.assertEqual(outcome["synced"], 1)

    def test_tai_len_that_bai_thi_xep_lai_hang_chu_khong_bao_xong(self):
        """Metadata đã lưu nhưng file chưa — chưa thể coi là xong."""
        class Hong(_Hub):
            def upload_document(self, *args, **kwargs):
                from app.sync.client import HubUnavailable
                raise HubUnavailable("mất mạng")

        outcome = runner.push_once(self.db, Hong(), "e1", log=lambda *a: None,
                                   cv_folder=self.cv_folder)
        self.assertEqual(outcome["uploaded"], 0)
        self.assertEqual(outcome["retry"], 1)
        self.assertEqual(outcome["synced"], 0)
        self.assertEqual(self.db.sync_stats()["pending"], 1)

    def test_khong_co_cv_folder_thi_khong_no(self):
        outcome = runner.push_once(self.db, _Hub(), "e1", log=lambda *a: None,
                                   cv_folder="")
        self.assertEqual(outcome["retry"], 1)

    def test_cung_noi_dung_trong_MOT_lo_chi_tai_len_mot_lan(self):
        """Một người nộp cùng CV cho hai cổng — rất hay gặp ở lần đồng bộ đầu.

        Hub tính needs_file cho cả lô TRƯỚC khi có lượt tải nào, nên nó không thể
        tự biết; Edge phải nhớ trong phạm vi lô.
        """
        # Lượt ứng tuyển thứ hai, file khác tên nhưng NỘI DUNG GIỐNG HỆT.
        self.db.upsert({"source": "vietnamworks", "account": "ta@msb.com.vn",
                        "cv_id": "2", "fullname": "Nguyễn Văn An",
                        "email": "an@example.com", "phone": "0901234567",
                        "applied_ts": "2026-08-02 09:00:00", "filename": "cv2.pdf",
                        "dl_status": "done"})
        with open(os.path.join(self.cv_folder, "cv2.pdf"), "wb") as handle:
            handle.write(self.content)
        now = "2026-08-02 09:00:00"
        self.db._write(
            """INSERT INTO candidate_documents
                 (source,account,cv_id,filename,file_hash,file_size,file_format,
                  parse_status,full_text,text_length,queued_at,updated_at)
               VALUES ('vietnamworks','ta@msb.com.vn','2','cv2.pdf',?,23,'pdf',
                       'done','t',1,?,?)""",
            (self.digest, now, now))
        self.db.commit()
        runner.scan_documents(self.db, self.cv_folder)

        hub = _Hub()
        outcome = runner.push_once(self.db, hub, "e1", log=lambda *a: None,
                                   cv_folder=self.cv_folder)
        self.assertEqual(len(hub.uploads), 1, "chỉ tải nội dung đó lên một lần")
        self.assertEqual(outcome["synced"], 2, "cả hai bản ghi vẫn xong")


if __name__ == "__main__":
    unittest.main()


class UploadGuardTest(unittest.TestCase):
    """Chặn trước những lượt tải lên chắc chắn hỏng.

    Hub từ chối cả hai trường hợp dưới đây bằng HTTP 400, mà 400 phải quay vòng
    đủ 8 lần rồi mới thành `failed` — hai tiếng thử lại một việc không bao giờ
    thành công, và cuối cùng vẫn mất.
    """

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.cv_folder = os.path.join(self.folder, "CV")
        os.makedirs(self.cv_folder)
        self.db = Database(os.path.join(self.folder, "test.db"),
                           log=lambda *a: None).open()
        self.addCleanup(self.db.close)

    def _row(self, content, claimed_digest):
        path = os.path.join(self.cv_folder, "cv.pdf")
        with open(path, "wb") as handle:
            handle.write(content)

        self.db.upsert({"source": "topcv", "account": "ta@msb.com.vn",
                        "cv_id": "1", "fullname": "Nguyễn Văn An",
                        "filename": "cv.pdf", "dl_status": "done"})
        now = "2026-08-01 09:00:00"
        self.db._write(
            """INSERT INTO candidate_documents
                 (source,account,cv_id,filename,file_hash,file_size,file_format,
                  parse_status,full_text,text_length,queued_at,updated_at)
               VALUES ('topcv','ta@msb.com.vn','1','cv.pdf',?,?,'pdf','done','t',1,?,?)""",
            (claimed_digest, len(content), now, now))
        self.db.commit()
        self.db.enqueue_sync("document", "topcv|ta@msb.com.vn|1", "h1")
        self.db.commit()
        return self.db.claim_sync_batch(1)[0]

    def test_file_qua_lon_bi_chan_NGAY_khong_thu_lai_8_lan(self):
        content = b"x" * (runner.MAX_UPLOAD_BYTES + 1)
        digest = hashlib.sha256(content).hexdigest()
        row = self._row(content, digest)

        sent = runner._upload_file(self.db, object(), row, {"sha256": digest},
                                   self.cv_folder, lambda *a: None)
        self.assertFalse(sent)
        self.assertEqual(self.db.sync_stats()["failed"], 1)

    def test_ma_bam_cu_bi_chan_truoc_khi_gui(self):
        """`file_hash` ghi lúc bóc tách; file bị thay dưới cùng tên thì nó đã cũ."""
        row = self._row(b"noi dung da doi", "a" * 64)

        sent = runner._upload_file(self.db, object(), row, {"sha256": "a" * 64},
                                   self.cv_folder, lambda *a: None)
        self.assertFalse(sent)
        self.assertEqual(self.db.sync_stats()["failed"], 1)
