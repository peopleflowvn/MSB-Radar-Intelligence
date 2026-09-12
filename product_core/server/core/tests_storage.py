# -*- coding: utf-8 -*-
"""Kiểm thử lớp lưu trữ file."""
import os
import shutil
import tempfile

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from .storage import LocalStorage, StorageError, build_storage, content_key, sha256_of


class ContentKeyTest(TestCase):
    def test_khoa_chia_nhanh_theo_ma_bam(self):
        digest = "ab" + "c" * 62
        self.assertEqual(content_key(digest, "cv.pdf"), f"ab/cc/{digest}.pdf")

    def test_giu_duoi_file(self):
        digest = "a" * 64
        self.assertTrue(content_key(digest, "ho so.DOCX").endswith(".docx"))

    def test_khong_co_duoi_van_hop_le(self):
        digest = "a" * 64
        self.assertEqual(content_key(digest), f"aa/aa/{digest}")

    def test_ma_bam_sai_thi_bao_loi(self):
        for bad in ("", "abc", "z" * 63, None):
            with self.assertRaises(StorageError):
                content_key(bad)

    def test_cung_noi_dung_cho_cung_khoa(self):
        """Cùng một CV tải từ TopCV và VietnamWorks chỉ chiếm một chỗ."""
        data = b"noi dung CV"
        self.assertEqual(content_key(sha256_of(data), "a.pdf"),
                         content_key(sha256_of(data), "a.pdf"))


class LocalStorageTest(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.storage = LocalStorage(self.root)
        self.data = b"noi dung CV thu nghiem"
        self.key = content_key(sha256_of(self.data), "cv.pdf")

    def test_luu_roi_doc_lai(self):
        self.storage.save(self.key, self.data)
        self.assertEqual(self.storage.read(self.key), self.data)

    def test_exists(self):
        self.assertFalse(self.storage.exists(self.key))
        self.storage.save(self.key, self.data)
        self.assertTrue(self.storage.exists(self.key))

    def test_size(self):
        self.storage.save(self.key, self.data)
        self.assertEqual(self.storage.size(self.key), len(self.data))

    def test_doc_file_khong_ton_tai_thi_bao_loi(self):
        with self.assertRaises(StorageError):
            self.storage.read(self.key)

    def test_xoa(self):
        self.storage.save(self.key, self.data)
        self.assertTrue(self.storage.delete(self.key))
        self.assertFalse(self.storage.delete(self.key), "xoá lần hai trả False")

    def test_ghi_de_cung_khoa_van_dung(self):
        self.storage.save(self.key, self.data)
        self.storage.save(self.key, self.data)
        self.assertEqual(self.storage.read(self.key), self.data)

    def test_khong_de_lai_file_tam(self):
        self.storage.save(self.key, self.data)
        thua = [name for _f, _d, files in os.walk(self.root)
                for name in files if name.endswith(".part")]
        self.assertEqual(thua, [])

    def test_chan_duyet_thu_muc(self):
        """Khoá đến từ dữ liệu, nên '../' phải bị chặn."""
        for bad in ("../../etc/passwd", "..\\..\\windows\\system32",
                    "a/../../../ngoai.txt"):
            with self.assertRaises(StorageError):
                self.storage.save(bad, b"x")

    def test_usage_bao_dung_luong(self):
        self.storage.save(self.key, self.data)
        usage = self.storage.usage()
        self.assertEqual(usage["backend"], "local")
        self.assertEqual(usage["stored_bytes"], len(self.data))
        self.assertGreater(usage["disk_free_bytes"], 0)

    def test_open_tra_ve_luong_doc_duoc(self):
        self.storage.save(self.key, self.data)
        with self.storage.open(self.key) as handle:
            self.assertEqual(handle.read(), self.data)


class BuildStorageTest(TestCase):
    def test_mac_dinh_la_local(self):
        self.assertIsInstance(build_storage({}), LocalStorage)

    def test_backend_la_thi_bao_loi(self):
        with self.assertRaises(ImproperlyConfigured):
            build_storage({"backend": "s3-cua-ai-do"})

    def test_r2_thieu_cau_hinh_thi_bao_ro_thieu_gi(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            build_storage({"backend": "r2", "bucket": "b"})
        for missing in ("account_id", "access_key", "secret_key"):
            self.assertIn(missing, str(ctx.exception))
