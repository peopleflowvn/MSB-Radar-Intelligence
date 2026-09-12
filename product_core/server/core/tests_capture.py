# -*- coding: utf-8 -*-
"""Số liệu thu thập và hợp nhất (Master Plan mục 9).

Những con số ở đây sẽ lên slide và được đọc to trước hội đồng giám khảo, nên
bài kiểm này canh kỹ hơn bình thường một bậc: mỗi con số phải **đúng nghĩa của
tên nó**, không chỉ "có giá trị khác 0".

Riêng `multi_source_people` là con số quan trọng nhất — nó là bằng chứng bằng
số cho câu *"Ba lượt hồ sơ, nhưng chỉ là một con người"*. Đếm sai câu đó thì
mất luôn khoảnh khắc trung tâm của phần demo.
"""
from io import StringIO

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from people.models import Document, Person

from accounts import roles

from . import capture
from .models import Edge, SourceRecord


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class ProviderCoverageTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        self.an = Person.objects.create(display_name="Nguyễn Văn An")

    def _record(self, source, key, person=None, status=SourceRecord.STATUS_RESOLVED):
        return SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record", entity_key=key,
            content_hash=key, source=source, person=person, status=status)

    def test_nguon_CHUA_co_du_lieu_van_hien_ra(self):
        """"TopCV chưa kết nối" là thông tin vận hành, không phải thứ để giấu."""
        self._record("topcv", "a1", person=self.an)
        rows = {row["source"]: row for row in capture.provider_coverage()}
        for source in capture.PROVIDER_LABELS:
            self.assertIn(source, rows, source)
        self.assertFalse(rows["itviec"]["connected"])
        self.assertEqual(rows["itviec"]["records"], 0)

    def test_dem_dung_ban_ghi_va_so_nguoi(self):
        binh = Person.objects.create(display_name="Trần Bình")
        self._record("topcv", "a1", person=self.an)
        self._record("topcv", "a2", person=self.an)   # cùng người, hai lượt
        self._record("topcv", "a3", person=binh)
        rows = {row["source"]: row for row in capture.provider_coverage()}
        self.assertEqual(rows["topcv"]["records"], 3)
        self.assertEqual(rows["topcv"]["people"], 2)

    def test_nguon_LA_van_hien_ra(self):
        """Dữ liệu vào hệ thống mà không ai biết từ đâu là điều tệ hơn."""
        self._record("nguon-moi-toanh", "x1", person=self.an)
        rows = {row["source"]: row for row in capture.provider_coverage()}
        self.assertIn("nguon-moi-toanh", rows)

    def test_dem_rieng_ban_ghi_chua_phan_giai(self):
        self._record("topcv", "a1", person=self.an)
        self._record("topcv", "a2", status=SourceRecord.STATUS_PENDING)
        rows = {row["source"]: row for row in capture.provider_coverage()}
        self.assertEqual(rows["topcv"]["pending"], 1)

    def test_xep_theo_so_ban_ghi_giam_dan(self):
        self._record("topcv", "a1", person=self.an)
        for index in range(3):
            self._record("vietnamworks", f"v{index}", person=self.an)
        rows = capture.provider_coverage()
        self.assertEqual(rows[0]["source"], "vietnamworks")


class ConsolidationTest(TestCase):
    """*"Ba lượt hồ sơ, nhưng chỉ là một con người"* — bằng số."""

    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        self.an = Person.objects.create(display_name="Nguyễn Văn An")

    def _record(self, source, key, person=None):
        return SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record", entity_key=key,
            content_hash=key, source=source, person=person,
            status=(SourceRecord.STATUS_RESOLVED if person
                    else SourceRecord.STATUS_PENDING))

    def test_dem_dung_nguoi_xuat_hien_o_NHIEU_NGUON(self):
        self._record("topcv", "a1", person=self.an)
        self._record("vietnamworks", "a2", person=self.an)
        self._record("careerviet", "a3", person=self.an)
        data = capture.consolidation()
        self.assertEqual(data["multi_source_people"], 1)
        self.assertEqual(data["max_sources_for_one_person"], 3)
        self.assertEqual(data["unique_people"], 1)

    def test_nhieu_luot_CUNG_MOT_nguon_KHONG_tinh_la_hop_nhat(self):
        """Ứng tuyển hai vị trí trên cùng TopCV không chứng minh gì về hợp nhất."""
        self._record("topcv", "a1", person=self.an)
        self._record("topcv", "a2", person=self.an)
        data = capture.consolidation()
        self.assertEqual(data["multi_source_people"], 0)
        self.assertEqual(data["max_sources_for_one_person"], 1)

    def test_ban_ghi_tren_mot_nguoi(self):
        binh = Person.objects.create(display_name="Trần Bình")
        self._record("topcv", "a1", person=self.an)
        self._record("vietnamworks", "a2", person=self.an)
        self._record("topcv", "b1", person=binh)
        data = capture.consolidation()
        self.assertEqual(data["records_per_person"], 1.5)

    def test_ban_ghi_chua_phan_giai_KHONG_lam_lech_ty_le(self):
        """Bản ghi chưa gộp được vào ai không được tính vào mẫu số."""
        self._record("topcv", "a1", person=self.an)
        self._record("topcv", "a2")          # chưa phân giải
        data = capture.consolidation()
        self.assertEqual(data["records_per_person"], 1.0)
        self.assertEqual(data["pending"], 1)
        self.assertEqual(data["source_records"], 2)

    def test_kho_rong_thi_khong_chia_cho_khong(self):
        data = capture.consolidation()
        self.assertIsNone(data["records_per_person"])
        self.assertEqual(data["unique_people"], 0)


class ParseQualityTest(TestCase):
    def setUp(self):
        self.an = Person.objects.create(display_name="Nguyễn Văn An")

    def _document(self, sha, status, storage_key=""):
        return Document.objects.create(
            person=self.an, sha256=sha, parse_status=status,
            storage_key=storage_key, filename=f"{sha}.pdf")

    def test_chua_co_tai_lieu_thi_tra_None_khong_phai_0(self):
        """"Chưa có gì" và "bóc tách hỏng hoàn toàn" là hai tình trạng khác nhau."""
        data = capture.parse_quality()
        self.assertIsNone(data["success_rate"])
        self.assertEqual(data["documents"], 0)

    def test_ty_le_boc_tach(self):
        self._document("h1", Document.PARSE_DONE)
        self._document("h2", Document.PARSE_DONE)
        self._document("h3", Document.PARSE_FAILED)
        self._document("h4", Document.PARSE_PENDING)
        data = capture.parse_quality()
        self.assertEqual(data["documents"], 4)
        self.assertEqual(data["parsed"], 2)
        self.assertEqual(data["failed"], 1)
        self.assertEqual(data["success_rate"], 0.5)

    def test_dem_rieng_file_da_co_tren_Hub(self):
        """Edge báo có CV mà chưa tải lên được là một tình trạng riêng."""
        self._document("h1", Document.PARSE_DONE, storage_key="ab/cd/h1")
        self._document("h2", Document.PARSE_DONE)
        self.assertEqual(capture.parse_quality()["stored"], 1)


class CaptureApiTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        self.an = Person.objects.create(display_name="Nguyễn Văn An")
        for source in ("topcv", "vietnamworks"):
            SourceRecord.objects.create(
                edge=self.edge, entity_type="source_record",
                entity_key=f"{source}-1", content_hash=f"{source}-1",
                source=source, person=self.an,
                status=SourceRecord.STATUS_RESOLVED)

    def test_moi_tai_khoan_dang_nhap_deu_xem_duoc(self):
        """Recruiter cần biết kho có gì trước khi tin vào kết quả tìm kiếm."""
        self.client.force_login(make_user("tuyendung-capture", roles.RECRUITER))
        response = self.client.get(reverse("hub-capture"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["consolidation"]["multi_source_people"], 1)
        self.assertTrue(body["providers"])

    def test_KHONG_lo_du_lieu_ca_nhan(self):
        """Toàn bộ phản hồi phải là số đếm, không có tên hay liên hệ nào."""
        self.client.force_login(make_user("rm-capture", roles.RB_SALES))
        payload = self.client.get(reverse("hub-capture")).content.decode("utf-8")
        self.assertNotIn("Nguyễn Văn An", payload)

    def test_chua_dang_nhap_bi_chan(self):
        self.assertIn(self.client.get(reverse("hub-capture")).status_code,
                      (401, 403))

    def test_trang_van_hanh_gom_ca_so_thu_thap(self):
        from reports import overview

        data = overview.collect()
        self.assertIn("capture", data)
        self.assertEqual(data["capture"]["consolidation"]["unique_people"], 1)


class SeedDemoCaptureTest(TestCase):
    """Dữ liệu demo phải làm các con số này KHÁC 0.

    Không có bài này thì `seed_demo` có thể lặng lẽ mất nhân vật đa nguồn, và
    màn hình thu thập sẽ hiện toàn số 0 đúng lúc đang demo trước hội đồng —
    thứ không ai phát hiện cho tới khi đứng trên sân khấu.
    """

    def test_seed_demo_tao_ra_nguoi_da_nguon(self):
        from django.core.management import call_command

        # Hứng stdout: lệnh in tiếng Việt, và console Windows dùng cp1252 sẽ
        # ném UnicodeEncodeError khi test runner bắt luồng ra. Lệnh chạy tay
        # vẫn bình thường — đây là chuyện của môi trường test, không phải lỗi
        # của lệnh.
        call_command("seed_demo", "--reset", stdout=StringIO())
        data = capture.consolidation()
        self.assertGreater(data["multi_source_people"], 0,
                           "Demo mất nhân vật đa nguồn — mất luôn khoảnh khắc "
                           "'ba lượt hồ sơ, một con người'")
        self.assertGreaterEqual(data["max_sources_for_one_person"], 3)
        self.assertGreater(data["records_per_person"], 1.0)

    def test_seed_demo_co_nhieu_nguon_dang_chay(self):
        from django.core.management import call_command

        # Hứng stdout: lệnh in tiếng Việt, và console Windows dùng cp1252 sẽ
        # ném UnicodeEncodeError khi test runner bắt luồng ra. Lệnh chạy tay
        # vẫn bình thường — đây là chuyện của môi trường test, không phải lỗi
        # của lệnh.
        call_command("seed_demo", "--reset", stdout=StringIO())
        connected = [row for row in capture.provider_coverage() if row["connected"]]
        self.assertGreaterEqual(len(connected), 3,
                                "Demo phải cho thấy dữ liệu về từ nhiều nền tảng")
