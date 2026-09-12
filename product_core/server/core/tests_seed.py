# -*- coding: utf-8 -*-
"""Lệnh dựng dữ liệu demo.

Lệnh này chạy vào sáng ngày Hackday, có thể trong lúc đang vội. Nên nó phải làm
đúng hai việc và không làm việc thứ ba: dựng đủ dữ liệu, dọn sạch dấu vết diễn
tập, và **không đụng vào dữ liệu không phải của nó**.
"""
from core.models import Edge, SourceRecord
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from hiring.models import HiringNeed
from people.models import Person


class SeedDemoTest(TestCase):
    def seed(self, **kwargs):
        call_command("seed_demo", quiet=True, **kwargs)

    def test_dung_du_tai_khoan_va_ung_vien(self):
        self.seed()
        self.assertEqual(User.objects.count(), 6)
        self.assertEqual(Person.objects.count(), 8)
        self.assertTrue(User.objects.get(username="admin").is_superuser)

    def test_chay_lai_KHONG_nhan_doi_du_lieu(self):
        """Chạy hai lần vì lo lắng là phản xạ bình thường lúc vội."""
        self.seed()
        self.seed()
        self.assertEqual(Person.objects.count(), 8)
        self.assertEqual(User.objects.count(), 6)

    def test_gop_dung_nguoi_ung_tuyen_ba_lan(self):
        self.seed()
        an = Person.objects.filter(display_name__contains="Nguyễn Văn An")
        self.assertEqual(an.count(), 1)
        self.assertEqual(an.first().source_records.count(), 3)

    def test_reset_don_ca_vi_tri_tuyen(self):
        """Xoá người xong mà giữ vị trí thì còn lại những vị trí rỗng — tệ hơn
        cả giữ nguyên. Và đây chính là chỗ vị trí diễn tập nằm lại."""
        self.seed()
        HiringNeed.objects.create(title="Vị trí diễn tập")
        self.seed(reset=True)
        self.assertEqual(HiringNeed.objects.count(), 0)
        self.assertEqual(Person.objects.count(), 8)

    def test_reset_KHONG_dung_du_lieu_cua_edge_khac(self):
        """Người chạy lệnh này gần như luôn có dữ liệu khác trong cùng CSDL."""
        khac = Edge.objects.create(label="Edge thật", edge_id="that-su")
        SourceRecord.objects.create(
            edge=khac, entity_type="source_record", entity_key="topcv|a|999",
            content_hash="h999", payload={"source": "topcv", "fullname": "Người thật"})

        self.seed(reset=True)
        self.assertTrue(Edge.objects.filter(edge_id="that-su").exists())
        self.assertTrue(SourceRecord.objects.filter(entity_key="topcv|a|999").exists())

    def test_moi_luot_ung_tuyen_co_mot_file_CV(self):
        """Thiếu bước này thì hồ sơ hiện “0 phiên bản CV” trên màn hình demo."""
        self.seed()
        an = Person.objects.get(display_name__contains="Nguyễn Văn An")
        self.assertEqual(an.documents.count(), 3)

    def test_ba_phien_ban_CV_xep_theo_NGAY_UNG_TUYEN(self):
        """Phần đáng xem nhất: cùng một người, CV đổi qua từng năm."""
        self.seed()
        an = Person.objects.get(display_name__contains="Nguyễn Văn An")
        theo_ban = {d.version_number(): d.source for d in an.documents.all()}
        self.assertEqual(theo_ban, {1: "topcv", 2: "vietnamworks", 3: "careerviet"})

    def test_noi_dung_CV_khac_nhau_giua_cac_luot(self):
        """Trùng nội dung thì kho theo mã băm gộp lại thành một tài liệu."""
        self.seed()
        an = Person.objects.get(display_name__contains="Nguyễn Văn An")
        self.assertEqual(len({d.sha256 for d in an.documents.all()}), 3)

    def test_file_CV_co_noi_dung_that(self):
        self.seed()
        an = Person.objects.get(display_name__contains="Nguyễn Văn An")
        for document in an.documents.all():
            self.assertGreater(document.file_size, 0)
            self.assertGreater(document.text_length, 0)

    def test_du_lieu_di_qua_dung_duong_that(self):
        """Tạo thẳng Person là bỏ qua chính phần phân giải định danh."""
        self.seed()
        for person in Person.objects.all():
            self.assertTrue(person.source_records.exists())
            self.assertTrue(person.identities.exists())
