# -*- coding: utf-8 -*-
"""Kiểm export.csv — chiều XUẤT của cùng template mà `intake-template` dùng
để NHẬP. Canh ba việc: (1) cột đúng khớp `fields.py`, (2) liên hệ luôn bị che
khi rời hệ thống, (3) file xuất ra nạp lại được bằng chính `normalize_row`.
"""
import csv
import io

from django.test import TestCase
from django.urls import reverse

from intel.facts import record_fact
from intel.models import ExtractedFact
from people.models import Person

from . import fields as fields_mod
from .tests import make_user

from accounts import roles


class ExportCandidatesTest(TestCase):
    def setUp(self):
        self.user = make_user("van-hanh", roles.EDGE_OPERATOR)
        self.client.force_login(self.user)

    def _get_rows(self):
        resp = self.client.get(reverse("intake-export"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        text = resp.content.decode("utf-8-sig")
        return list(csv.reader(io.StringIO(text)))

    def test_cot_dung_khop_fields_py(self):
        rows = self._get_rows()
        self.assertEqual(rows[0], fields_mod.template_headers())

    def test_lien_he_luon_bi_che(self):
        Person.objects.create(display_name="Ứng Viên Test",
                              primary_email="test@example.com",
                              primary_phone="+84901234567")
        rows = self._get_rows()
        header = rows[0]
        body = rows[1:]
        self.assertEqual(len(body), 1)
        record = dict(zip(header, body[0]))
        self.assertNotEqual(record["Email"], "test@example.com")
        self.assertNotEqual(record["Số điện thoại"], "+84901234567")
        self.assertIn("Ứng Viên Test", record["Họ tên"])

    def test_nguoi_da_gop_khong_xuat_lai(self):
        goc = Person.objects.create(display_name="Người Gốc")
        Person.objects.create(display_name="Người Đã Gộp", merged_into=goc)
        rows = self._get_rows()
        names = [dict(zip(rows[0], r))["Họ tên"] for r in rows[1:]]
        self.assertIn("Người Gốc", names)
        self.assertNotIn("Người Đã Gộp", names)

    def test_fact_da_duyet_len_dung_cot(self):
        person = Person.objects.create(display_name="Có Kỹ Năng")
        record_fact(person, "skills", "Python", source_kind=ExtractedFact.SOURCE_AI,
                   confidence=0.95)
        rows = self._get_rows()
        record = dict(zip(rows[0], next(
            r for r in rows[1:] if r[0] == "Có Kỹ Năng")))
        self.assertIn("Python", record["Kỹ năng"])

    def test_xuat_ra_nap_lai_khong_loi_dinh_dang(self):
        """Vòng tròn export -> import: mỗi ô đã qua `normalize_row` không báo lỗi."""
        person = Person.objects.create(display_name="Vòng Tròn",
                                       primary_email="vong@example.com")
        record_fact(person, "city", "Hà Nội", source_kind=ExtractedFact.SOURCE_AI,
                   confidence=0.9)
        rows = self._get_rows()
        header = rows[0]
        record = dict(zip(header, next(
            r for r in rows[1:] if r[0] == "Vòng Tròn")))
        fields, errors = fields_mod.normalize_row(record)
        self.assertEqual(errors, {})
