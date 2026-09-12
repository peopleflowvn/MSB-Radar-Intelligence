# -*- coding: utf-8 -*-
"""Đối chiếu cột với template CV của nền tảng ngoài (chủ dự án cung cấp 05/09).

Không kiểm "mọi cột nhận diện được nói chung" — `intake/tests.py` đã làm việc
đó. Bài này canh ĐÚNG một việc: file CSV thật của nền tảng khác phải nạp được
mà không cần map tay, để hai bên "ăn khớp nhau và thừa hưởng dữ liệu của nhau".
"""
from django.test import TestCase

from . import fields as fields_mod

#: Nguyên văn 23 cột trong file mẫu chủ dự án gửi (05/09/2026), theo đúng thứ tự.
EXTERNAL_TEMPLATE_HEADERS = [
    "Timestamp", "Tên file gốc", "Trạng thái", "Mức độ ưu tiên",
    "Tên ứng viên", "Email", "SĐT", "Giới tính", "Ngày sinh",
    "Khu vực ứng tuyển", "Địa chỉ hiện tại", "Trình độ", "Trường",
    "Chuyên ngành", "GPA", "Năm tốt nghiệp", "Kinh nghiệm", "Kỹ năng",
    "Thành tích", "Chứng chỉ", "Trình độ ngoại ngữ", "Thông tin khác",
    "Đánh giá chi tiết",
]

#: Bốn cột KHÔNG khớp field nào, CỐ Ý: trạng thái/mức ưu tiên/tên file/mốc thời
#: gian là thông tin xử lý của NỀN TẢNG KHÁC, không phải dữ kiện về ứng viên.
#: "Tên file gốc" khớp `cv_file_name` (đã có alias) nên KHÔNG nằm trong danh
#: sách bỏ qua.
_EXPECTED_UNMAPPED = {"Timestamp", "Trạng thái", "Mức độ ưu tiên"}


class ExternalTemplateCompatTest(TestCase):
    def test_moi_cot_deu_khop_hoac_biet_ro_vi_sao_bo_qua(self):
        unmapped = [h for h in EXTERNAL_TEMPLATE_HEADERS
                   if fields_mod.column_for_header(h) is None]
        self.assertEqual(set(unmapped), _EXPECTED_UNMAPPED,
                         f"Cột lạ chưa được xếp loại: {set(unmapped) - _EXPECTED_UNMAPPED}")

    def test_ngay_sinh_day_du_khac_nam_sinh_khong_gop_lam_mot(self):
        """Mất độ chính xác nếu ép ngày thành năm — giữ hai cột riêng."""
        ngay = fields_mod.column_for_header("Ngày sinh")
        nam = fields_mod.column_for_header("Năm sinh")
        self.assertEqual(ngay.key, "birth_date")
        self.assertEqual(nam.key, "birth_year")
        self.assertNotEqual(ngay.key, nam.key)

    def test_khu_vuc_ung_tuyen_khac_dia_chi_hien_tai(self):
        """Nơi Ở khác nơi ỨNG TUYỂN — không được gộp chung."""
        khu_vuc = fields_mod.column_for_header("Khu vực ứng tuyển")
        dia_chi = fields_mod.column_for_header("Địa chỉ hiện tại")
        self.assertEqual(khu_vuc.key, "applied_region")
        self.assertEqual(dia_chi.key, "address")

    def test_danh_gia_chi_tiet_la_phan_doan_khong_phai_fact(self):
        """Trường nhận xét từ nguồn ngoài — không nằm trong field_rules.py vì
        đó là một PHÁN ĐOÁN đã thành hình, không phải dữ kiện quan sát được."""
        from intel.field_rules import KNOWN_FIELDS
        col = fields_mod.column_for_header("Đánh giá chi tiết")
        self.assertEqual(col.key, "external_assessment")
        self.assertNotIn("external_assessment", KNOWN_FIELDS)

    def test_khong_co_alias_trung_nhau_trong_toan_bo_danh_sach(self):
        """Trùng alias là lỗi ÂM THẦM: cột A vô tình nuốt mất tiêu đề của cột B,
        và người nhập liệu không có cách nào biết vì sao dữ liệu lệch cột."""
        seen = {}
        for col in fields_mod.COLUMNS:
            for name in (col.header, *col.aliases):
                key = fields_mod.normalize_header(name)
                if key in seen and seen[key] is not col:
                    self.fail(f"Alias trùng: {name!r} thuộc cả "
                             f"{seen[key].key!r} và {col.key!r}")
                seen[key] = col

    def test_dong_du_lieu_that_nap_duoc_khong_loi_dinh_dang(self):
        """Không chỉ khớp TÊN cột — giá trị THẬT trong file mẫu phải qua được
        `normalize_row` không lỗi, kể cả ngày viết kiểu dd/mm/yyyy."""
        raw = {
            "Tên ứng viên": "Nông Thị Quỳnh Anh",
            "Email": "anhntq77@gmail.com",
            "SĐT": "0855692599",
            "Giới tính": "Nữ",
            "Ngày sinh": "01/05/1988",
            "Khu vực ứng tuyển": "Hà Nội",
            "GPA": "3.2",
            "Năm tốt nghiệp": "2010",
        }
        fields, errors = fields_mod.normalize_row(raw)
        self.assertEqual(errors, {})
        self.assertEqual(fields["birth_date"], "1988-05-01")
        self.assertEqual(fields["applied_region"], "Hà Nội")
        self.assertEqual(fields["phone"], "+84855692599")
