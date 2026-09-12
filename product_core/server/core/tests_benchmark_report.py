# -*- coding: utf-8 -*-
"""benchmark_report — không bịa số, chỉ in lại những gì đếm được thật.

Không kiểm tra giá trị cụ thể (phụ thuộc dữ liệu demo, có thể đổi) — chỉ kiểm
lệnh chạy được trên kho rỗng lẫn kho có dữ liệu, và không crash ở mục 3.3 khi
chưa có Person nào (mẫu số bằng 0 là tình huống thật, không phải lỗi).
"""
import io

from django.core.management import call_command
from django.test import TestCase

from core.models import Edge, SourceRecord
from people.models import Person


class BenchmarkReportTest(TestCase):
    def run_command(self):
        out = io.StringIO()
        call_command("benchmark_report", stdout=out)
        return out.getvalue()

    def test_kho_rong_khong_crash(self):
        output = self.run_command()
        self.assertIn("Loại A", output)
        self.assertIn("Chưa có Person nào đã hợp nhất", output)

    def test_co_du_lieu_in_dung_so(self):
        edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        person = Person.objects.create(display_name="Nguyễn Văn An")
        SourceRecord.objects.create(
            edge=edge, entity_type="application", entity_key="k1",
            source="topcv", content_hash="h1", person=person,
            status=SourceRecord.STATUS_RESOLVED)
        SourceRecord.objects.create(
            edge=edge, entity_type="application", entity_key="k2",
            source="vietnamworks", content_hash="h2", person=person,
            status=SourceRecord.STATUS_RESOLVED)

        output = self.run_command()
        self.assertIn("Bản ghi nguồn đã nhận", output)
        self.assertIn("Person đã hợp nhất: 1, cũ hơn 12 tháng: 0", output)
