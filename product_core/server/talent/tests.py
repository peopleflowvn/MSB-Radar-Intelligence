# -*- coding: utf-8 -*-
"""Kiểm thử Talent Radar (Phase 6).

Hai điều quan trọng nhất được canh ở đây:

1. **Suy diễn không được ghi đè kiến thức của recruiter.** Người đã nói chuyện với
   ứng viên biết rõ hơn bất kỳ CV nào.
2. **Bộ lọc chạy giống nhau trên SQLite và PostgreSQL.** Chỉ phần tìm chữ tự do khác;
   test viết sao cho không phụ thuộc backend.
"""
import json

from django.contrib.auth.models import User
from django.db.models import F
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import Edge, SourceRecord
from people import ingest, resolution
from people.models import Document, Interaction, Person, Relationship

from . import derive as derive_module
from . import search as search_module
from .models import Pool, PoolMembership, Tag, TalentProfile


def payload(cv_id="1", **overrides):
    data = {
        "source": "topcv", "account": "ta@msb.com.vn", "cv_id": cv_id,
        "fullname": "Nguyễn Văn An", "email": "an@example.com", "phone": "0901234567",
        "position": "Data Analyst", "current_title": "Data Analyst",
        "last_company": "Ngân hàng ABC", "skills": "SQL, Python, Power BI",
        "years_experience": "3 năm", "city": "Hà Nội", "education": "Đại học Kinh tế",
        "applied_ts": "2026-08-01 09:00:00",
    }
    data.update(overrides)
    return data


class ParseTest(TestCase):
    def test_tach_ky_nang_theo_dau_phan_cach(self):
        self.assertEqual(derive_module.parse_skills("SQL, Python; Power BI"),
                         ["SQL", "Python", "Power BI"])

    def test_khong_tach_theo_khoang_trang(self):
        """'Machine Learning' là một kỹ năng, không phải hai."""
        self.assertEqual(derive_module.parse_skills("Machine Learning"),
                         ["Machine Learning"])

    def test_bo_ky_nang_trung_khong_phan_biet_hoa_thuong(self):
        self.assertEqual(derive_module.parse_skills("SQL, sql, Sql"), ["SQL"])

    def test_nhan_ca_danh_sach_lan_chuoi(self):
        self.assertEqual(derive_module.parse_skills(["SQL", "Python"]), ["SQL", "Python"])

    def test_doc_so_nam_kinh_nghiem_tu_chuoi_tu_do(self):
        for text, expected in (("3 năm", 3.0), ("5 years", 5.0), ("hơn 2 năm", 2.0),
                               ("4", 4.0), ("2.5 năm", 2.5), ("2,5 năm", 2.5)):
            self.assertEqual(derive_module.parse_years(text), expected, text)

    def test_loai_so_nam_vo_ly(self):
        """CV có người gõ nhầm năm sinh vào ô kinh nghiệm."""
        self.assertIsNone(derive_module.parse_years("1990"))
        self.assertIsNone(derive_module.parse_years(-5))

    def test_khong_doc_duoc_thi_tra_none(self):
        for value in ("", None, "không rõ"):
            self.assertIsNone(derive_module.parse_years(value))


class DeriveTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")

    def _record(self, cv_id="1", **overrides):
        data = payload(cv_id, **overrides)
        record = SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key=f"{data['source']}|{data['account']}|{cv_id}",
            payload=data, content_hash=f"h{cv_id}", source=data["source"],
            fullname=data["fullname"], email=data["email"], phone=data["phone"])
        return record

    def test_suy_ho_so_tu_ban_ghi_nguon(self):
        self._record()
        ingest.resolve_pending()
        profile = TalentProfile.objects.get()
        self.assertEqual(profile.current_title, "Data Analyst")
        self.assertEqual(profile.current_company, "Ngân hàng ABC")
        self.assertEqual(profile.years_experience, 3.0)
        self.assertEqual(profile.skills, ["SQL", "Python", "Power BI"])

    def test_vi_tri_ung_tuyen_khong_thanh_chuc_danh_hien_tai(self):
        """`position` ở Edge là vị trí ỨNG TUYỂN — prod 19/09: 809/1019 hồ sơ bị ghi nhầm."""
        self._record(position="Giám đốc phòng giao dịch - RB - MSB - 1D", current_title="")
        ingest.resolve_pending()
        self.assertEqual(TalentProfile.objects.get().current_title, "")

    def test_go_chuc_danh_cu_da_ghi_nham_tu_vi_tri_ung_tuyen(self):
        self._record(position="Finance Analyst - QLTC - MSB - 3K057", current_title="")
        ingest.resolve_pending()
        person = Person.objects.get()
        TalentProfile.objects.filter(person=person).update(
            current_title="Finance Analyst - QLTC - MSB - 3K057")
        derive_module.derive(person)
        self.assertEqual(TalentProfile.objects.get().current_title, "")

    def test_tieu_de_ho_so_la_ten_tin_dang_thi_bo(self):
        """careerviet/vieclam24h: ô tiêu đề hồ sơ đôi khi chứa chính tên tin đăng."""
        job = "[RVI] Chuyên viên phát triển khách hàng cá nhân - RB - MSB - 1O330"
        self._record(position=job, current_title=job)
        ingest.resolve_pending()
        self.assertEqual(TalentProfile.objects.get().current_title, "")

    def test_ho_so_mat_ban_ghi_nguon_van_go_ten_tin_dang(self):
        job = "Finance Analyst - QLTC - MSB - 3K057"
        person = Person.objects.create(display_name="Mồ Côi", headline=job)
        TalentProfile.objects.create(person=person, current_title=job)
        derive_module.derive(person)
        self.assertEqual(TalentProfile.objects.get(person=person).current_title, "")

    def test_ban_ghi_moi_nhat_thang(self):
        self._record("1", applied_ts="2024-01-01 09:00:00",
                     current_title="Junior Analyst")
        self._record("2", applied_ts="2026-08-01 09:00:00",
                     current_title="Senior Data Analyst")
        ingest.resolve_pending()
        self.assertEqual(TalentProfile.objects.get().current_title, "Senior Data Analyst")

    def test_sap_theo_ngay_ung_tuyen_chu_khong_theo_luc_hub_nhan(self):
        """Một CV cũ tải về hôm nay vẫn là CV cũ — lỗi dễ mắc nhất ở đây."""
        self._record("1", applied_ts="2026-08-01 09:00:00", current_title="Mới")
        ingest.resolve_pending()
        # Bản ghi CŨ được nhận SAU
        self._record("2", applied_ts="2020-01-01 09:00:00", current_title="Cũ")
        ingest.resolve_pending()
        self.assertEqual(TalentProfile.objects.get().current_title, "Mới")

    def test_ky_nang_duoc_GOP_qua_moi_ban_ghi(self):
        """Người từng dùng SQL ba năm trước vẫn biết SQL, dù CV mới không nhắc."""
        self._record("1", applied_ts="2024-01-01 09:00:00", skills="SQL, Excel")
        self._record("2", applied_ts="2026-08-01 09:00:00", skills="Python, Airflow")
        ingest.resolve_pending()
        skills = TalentProfile.objects.get().skills
        for expected in ("SQL", "Excel", "Python", "Airflow"):
            self.assertIn(expected, skills)

    def test_truong_trong_thi_lay_ban_ghi_cu_hon(self):
        self._record("1", applied_ts="2024-01-01 09:00:00", education="Đại học Kinh tế")
        self._record("2", applied_ts="2026-08-01 09:00:00", education="")
        ingest.resolve_pending()
        self.assertEqual(TalentProfile.objects.get().education, "Đại học Kinh tế")

    def test_suy_cac_truong_mong_muon_tu_ban_ghi_nguon(self):
        """Các trường "mong muốn"/"tình trạng hôn nhân" Edge bóc từ trang chi
        tiết ứng viên (xem edge mục 41) - đồng bộ vào TalentProfile như mọi
        trường khác, cắt theo max_length của cột."""
        self._record(
            "1",
            desired_location="Đà Nẵng, Hồ Chí Minh",
            desired_level="Trưởng phòng",
            desired_position="Ngân hàng",
            job_type="Bán thời gian, Thời vụ",
            foreign_language="Tiếng Anh - Cao cấp",
            marital_status="Đã kết hôn",
            current_salary="1,500 (USD/tháng)")
        ingest.resolve_pending()
        profile = TalentProfile.objects.get()
        self.assertEqual(profile.desired_location, "Đà Nẵng, Hồ Chí Minh")
        self.assertEqual(profile.desired_level, "Trưởng phòng")
        self.assertEqual(profile.desired_position, "Ngân hàng")
        self.assertEqual(profile.job_type, "Bán thời gian, Thời vụ")
        self.assertEqual(profile.foreign_language, "Tiếng Anh - Cao cấp")
        self.assertEqual(profile.marital_status, "Đã kết hôn")
        self.assertEqual(profile.current_salary, "1,500 (USD/tháng)")

    def test_truong_mong_muon_qua_dai_bi_cat_theo_max_length(self):
        self._record("1", marital_status="X" * 100)  # cột chỉ 40 ký tự
        ingest.resolve_pending()
        self.assertEqual(len(TalentProfile.objects.get().marital_status), 40)

    def test_KHONG_ghi_de_truong_recruiter_da_sua(self):
        """Đây là bảo đảm quan trọng nhất của cả module."""
        self._record("1")
        ingest.resolve_pending()

        profile = TalentProfile.objects.get()
        profile.current_title = "Trưởng nhóm Dữ liệu (recruiter xác nhận)"
        profile.mark_curated("current_title")
        profile.save()

        self._record("2", applied_ts="2026-09-01 09:00:00", current_title="Data Analyst")
        ingest.resolve_pending()

        profile.refresh_from_db()
        self.assertEqual(profile.current_title, "Trưởng nhóm Dữ liệu (recruiter xác nhận)")

    def test_truong_khac_van_duoc_cap_nhat_binh_thuong(self):
        self._record("1")
        ingest.resolve_pending()
        profile = TalentProfile.objects.get()
        profile.current_title = "Do người sửa"
        profile.mark_curated("current_title")
        profile.save()

        self._record("2", applied_ts="2026-09-01 09:00:00",
                     current_title="Bị bỏ qua", last_company="Công ty Mới")
        ingest.resolve_pending()

        profile.refresh_from_db()
        self.assertEqual(profile.current_title, "Do người sửa")
        self.assertEqual(profile.current_company, "Công ty Mới")

    def test_suy_lai_nhieu_lan_cho_cung_ket_qua(self):
        self._record()
        ingest.resolve_pending()
        first = TalentProfile.objects.get()
        skills_before = list(first.skills)
        derive_module.derive(first.person)
        derive_module.derive(first.person)
        first.refresh_from_db()
        self.assertEqual(first.skills, skills_before)

    def test_khong_co_ban_ghi_nguon_thi_khong_no(self):
        person = Person.objects.create(display_name="Không nguồn")
        profile = derive_module.derive(person)
        self.assertEqual(profile.skills, [])


class DoiViecSinhSignalTest(TestCase):
    """Trước đây KHÔNG có gì sinh Signal từ luồng đồng bộ Edge → Hub. Một ứng
    viên đổi công ty giữa hai lượt ứng tuyển là tín hiệu bán hàng mạnh."""

    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")

    def _record(self, cv_id, **overrides):
        data = payload(cv_id, **overrides)
        return SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key=f"topcv|ta@msb.com.vn|{cv_id}", payload=data,
            content_hash=f"h{cv_id}", source="topcv", fullname=data["fullname"],
            email=data["email"], phone=data["phone"])

    def test_doi_cong_ty_giua_hai_luot_thi_sinh_signal_rb(self):
        from people.models import Signal
        from rb.models import OpportunitySuggestion
        self._record("1", applied_ts="2024-01-01 09:00:00", last_company="Vietcombank")
        self._record("2", applied_ts="2026-08-01 09:00:00", last_company="Techcombank")
        ingest.resolve_pending()
        sig = Signal.objects.get(signal_type="job_change")
        self.assertEqual(sig.domain, Signal.DOMAIN_RB)
        self.assertEqual(sig.evidence["tu_cong_ty"], "Vietcombank")
        self.assertEqual(sig.evidence["sang_cong_ty"], "Techcombank")
        # route_signal chạy: "tài khoản lương" trong reason -> đề xuất PAYROLL.
        self.assertTrue(OpportunitySuggestion.objects.filter(
            person=sig.person, product="payroll").exists())

    def test_cung_cong_ty_thi_khong_sinh_gi(self):
        from people.models import Signal
        self._record("1", applied_ts="2024-01-01 09:00:00", last_company="Vietcombank")
        self._record("2", applied_ts="2026-08-01 09:00:00", last_company="Vietcombank")
        ingest.resolve_pending()
        self.assertFalse(Signal.objects.filter(signal_type="job_change").exists())

    def test_mot_luot_duy_nhat_khong_sinh_gi(self):
        from people.models import Signal
        self._record("1", last_company="Vietcombank")
        ingest.resolve_pending()
        self.assertFalse(Signal.objects.filter(signal_type="job_change").exists())

    def test_suy_lai_khong_de_them_signal_trung(self):
        from people.models import Signal
        self._record("1", applied_ts="2024-01-01 09:00:00", last_company="Vietcombank")
        self._record("2", applied_ts="2026-08-01 09:00:00", last_company="Techcombank")
        ingest.resolve_pending()
        person = Signal.objects.get(signal_type="job_change").person
        derive_module.derive(person)
        derive_module.derive(person)
        self.assertEqual(Signal.objects.filter(signal_type="job_change").count(), 1)

    def test_placeholder_khong_tinh_la_doi_viec(self):
        from people.models import Signal
        self._record("1", applied_ts="2024-01-01 09:00:00", last_company="Vietcombank")
        self._record("2", applied_ts="2026-08-01 09:00:00", last_company="Đang cập nhật")
        ingest.resolve_pending()
        self.assertFalse(Signal.objects.filter(signal_type="job_change").exists())


class ApplyExtractedFactsTest(TestCase):
    """Fact AI bóc từ TEXT CV phải chảy vào TalentProfile — nếu không, "một đoạn
    văn bản dài" của Edge chỉ tra được bằng LIKE '%...%', không có cột nào.
    """

    def setUp(self):
        self.person = Person.objects.create(display_name="Lê Thị B")
        self.profile = TalentProfile.objects.create(
            person=self.person, current_title="", skills=[])

    _seq = 0

    def _fact(self, field, value, **kw):
        from intel.models import ExtractedFact
        ApplyExtractedFactsTest._seq += 1
        return ExtractedFact.objects.create(
            person=self.person, field=field, raw_value=value,
            normalized_value=kw.get("normalized", ""),
            source_kind=kw.get("source_kind", ExtractedFact.SOURCE_AI),
            status=ExtractedFact.STATUS_ACCEPTED, is_current=True,
            confidence=kw.get("confidence", 0.9),
            fingerprint=f"fp-{ApplyExtractedFactsTest._seq}")

    def test_lap_cot_con_trong_tu_fact(self):
        self._fact("current_title", "Chuyên viên Tín dụng")
        self._fact("education_level", "Đại học")
        self._fact("skills", "Thẩm định tín dụng")
        self._fact("skills", "Excel")
        self._fact("languages", "Tiếng Anh")
        self._fact("years_experience", "5 năm")

        derive_module.apply_extracted_facts(self.person)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_title, "Chuyên viên Tín dụng")
        self.assertEqual(self.profile.education, "Đại học")
        self.assertIn("Excel", self.profile.skills)
        self.assertIn("Thẩm định tín dụng", self.profile.skills)
        self.assertEqual(self.profile.foreign_language, "Tiếng Anh")
        self.assertEqual(self.profile.years_experience, 5.0)

    def test_payload_thang_fact_khong_de_len_gia_tri_da_co(self):
        self.profile.current_title = "Giám đốc Chi nhánh"   # derive() điền từ payload
        self.profile.save()
        self._fact("current_title", "Nhân viên")            # CV cũ nói khác

        derive_module.apply_extracted_facts(self.person)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_title, "Giám đốc Chi nhánh")

    def test_curated_mien_nhiem(self):
        self.profile.location = "Hà Nội"
        self.profile.mark_curated("location")
        self.profile.save()
        self._fact("city", "TP HCM")

        derive_module.apply_extracted_facts(self.person)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.location, "Hà Nội")

    def test_skills_hop_nhat_khong_trung(self):
        self.profile.skills = ["Excel", "SQL"]
        self.profile.save()
        self._fact("skills", "excel")          # trùng, khác hoa thường
        self._fact("skills", "Python")

        derive_module.apply_extracted_facts(self.person)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.skills.count("Excel"), 1)
        self.assertIn("Python", self.profile.skills)

    def test_chay_lai_cho_cung_ket_qua(self):
        self._fact("current_title", "Chuyên viên")
        derive_module.apply_extracted_facts(self.person)
        derive_module.apply_extracted_facts(self.person)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_title, "Chuyên viên")

    def test_hien_thi_nguyen_van_co_dau_khong_phai_dang_chuan_hoa(self):
        """Prod 19/09: 75 chức danh hiện "giam doc kinh doanh"."""
        self._fact("current_title", "Giám đốc Kinh doanh", normalized="giam doc kinh doanh")
        derive_module.apply_extracted_facts(self.person)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_title, "Giám đốc Kinh doanh")

    def test_sua_gia_tri_khong_dau_do_ban_cu_ghi(self):
        self.profile.current_title = "giam doc kinh doanh"
        self.profile.save()
        self._fact("current_title", "Giám đốc Kinh doanh", normalized="giam doc kinh doanh")
        derive_module.apply_extracted_facts(self.person)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_title, "Giám đốc Kinh doanh")

    def test_khong_co_profile_thi_khong_no(self):
        orphan = Person.objects.create(display_name="Chưa có hồ sơ")
        self.assertIsNone(derive_module.apply_extracted_facts(orphan))


class SearchTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        self._make("An", "an@example.com", "0901111111", "Data Analyst",
                   "SQL, Python", "Hà Nội", "3 năm")
        self._make("Bình", "binh@example.com", "0902222222", "Business Analyst",
                   "SQL, Excel", "Hồ Chí Minh", "7 năm")
        self._make("Cường", "cuong@example.com", "0903333333", "Backend Engineer",
                   "Java, Spring", "Hà Nội", "10 năm")
        ingest.resolve_pending()

    def _make(self, name, email, phone, title, skills, city, years):
        data = payload(cv_id=email[:3], fullname=f"Nguyễn Văn {name}", email=email,
                       phone=phone, current_title=title, position=title,
                       skills=skills, city=city, years_experience=years)
        SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key=f"topcv|ta@msb.com.vn|{email}", payload=data,
            content_hash=f"h{email}", source="topcv", fullname=data["fullname"],
            email=email, phone=phone)

    def test_khong_loc_gi_thi_tra_ve_het(self):
        total, rows = search_module.search()
        self.assertEqual(total, 3)
        self.assertEqual(len(rows), 3)

    def test_loc_theo_ky_nang(self):
        total, _ = search_module.search(skills=["SQL"])
        self.assertEqual(total, 2)

    def test_nhieu_ky_nang_la_AND_khong_phai_OR(self):
        """'SQL và Python' phải là cả hai."""
        total, _ = search_module.search(skills=["SQL", "Python"])
        self.assertEqual(total, 1)

    def test_ky_nang_khop_theo_tu_khong_nham_sql_voi_nosql(self):
        self._make("Dũng", "dung@example.com", "0905555555", "Data Engineer",
                   "NoSQL, MongoDB", "Hà Nội", "4 năm")
        ingest.resolve_pending()
        total, rows = search_module.search(skills=["SQL"])
        self.assertEqual(total, 2)
        self.assertNotIn("Nguyễn Văn Dũng", {row.display_name for row in rows})

    def test_loc_cac_thuoc_tinh_ho_so_mo_rong_va_ket_hop_and(self):
        person = Person.objects.get(display_name__contains="Bình")
        profile = person.talent_profile
        profile.desired_location = "Hà Nội"
        profile.seniority = "Senior"
        profile.education = "Đại học Kinh tế Quốc dân"
        profile.job_type = "Toàn thời gian"
        profile.foreign_language = "Tiếng Anh IELTS 7.0"
        profile.save()
        total, rows = search_module.search(
            desired_location="Hà Nội", seniority="Senior", education="Kinh tế",
            job_type='"Toàn thời gian"', foreign_language="IELTS")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0], person)

    def test_loc_theo_noi_o(self):
        total, _ = search_module.search(location="Hà Nội")
        self.assertEqual(total, 2)

    def test_loc_khac_cach_viet_van_khop(self):
        """Bình lưu ở "Hồ Chí Minh" — hỏi "Sài Gòn" vẫn phải ra đúng người đó."""
        total, rows = search_module.search(location="Sài Gòn")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0].display_name, "Nguyễn Văn Bình")

    def test_loc_van_ho_tro_cu_phap_boolean_khi_nguoi_dung_tu_go(self):
        """Không được để việc mở rộng đồng nghĩa đè lên cú pháp AND/OR đã có."""
        total, _ = search_module.search(location='"Hà Nội" OR "Hồ Chí Minh"')
        self.assertEqual(total, 3)

    def test_loc_theo_chuc_danh(self):
        total, _ = search_module.search(title="Analyst")
        self.assertEqual(total, 2)

    def test_loc_theo_khoang_so_nam_kinh_nghiem(self):
        total, _ = search_module.search(min_years=5)
        self.assertEqual(total, 2)
        total, _ = search_module.search(min_years=5, max_years=8)
        self.assertEqual(total, 1)

    def test_tim_chu_tu_do(self):
        total, _ = search_module.search(text="Cường")
        self.assertEqual(total, 1)

    def test_tim_khong_dau_van_ra_ket_qua_co_dau(self):
        """Gõ 'nguyen' phải ra 'Nguyễn'."""
        total, _ = search_module.search(text="nguyen")
        self.assertEqual(total, 3)

    def test_khop_theo_TU_chu_khong_phai_chuoi_con(self):
        """'An' là tên riêng rất phổ biến; nó không được khớp 'Analyst'.

        Đây cũng là điều giữ cho nhánh SQLite hành xử giống PostgreSQL, nơi
        SearchQuery khớp theo lexeme.
        """
        self._make("An", "an2@example.com", "0904444444", "Data Analyst",
                   "R", "Đà Nẵng", "1 năm")
        ingest.resolve_pending()

        total, rows = search_module.search(text="An")
        self.assertEqual(total, 2, "chỉ hai người TÊN An, không phải mọi Analyst")
        for person in rows:
            self.assertIn("An", person.display_name)

    def test_chuoi_tim_kiem_khong_bi_hieu_la_regex(self):
        """Người dùng gõ ký tự đặc biệt không được làm vỡ truy vấn."""
        for needle in ("(", "[a-z]", ".*", "\\"):
            total, _ = search_module.search(text=needle)
            self.assertEqual(total, 0)

    def test_ket_hop_nhieu_bo_loc(self):
        total, _ = search_module.search(skills=["SQL"], location="Hà Nội")
        self.assertEqual(total, 1)

    def test_loc_theo_kha_nang_lien_he(self):
        person = Person.objects.filter(display_name__contains="An").first()
        person.primary_phone = ""
        person.save()
        total, _ = search_module.search(has_phone=True)
        self.assertEqual(total, 2)

    def test_rm_loc_theo_san_pham_trang_thai_va_co_hoi(self):
        from rb.models import ProductInterest, RBOpportunity, RBProfile
        person = Person.objects.get(display_name__contains="An")
        profile = RBProfile.objects.create(person=person, lead_status="interested",
                                           employer="MSB")
        ProductInterest.objects.create(
            profile=profile, product="mortgage", confidence=0.8,
            observed_at=timezone.now())
        RBOpportunity.objects.create(person=person, product="mortgage")
        total, rows = search_module.search(
            product_interest="mortgage", lead_status="interested",
            has_open_opportunity=True)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0], person)
        self.assertEqual(search_module.search(text="MSB")[0], 1)

    def test_phan_trang(self):
        total, rows = search_module.search(limit=2)
        self.assertEqual(total, 3)
        self.assertEqual(len(rows), 2)
        _, rows = search_module.search(limit=2, offset=2)
        self.assertEqual(len(rows), 1)

    def test_chan_tren_limit(self):
        _, rows = search_module.search(limit=99999)
        self.assertLessEqual(len(rows), search_module.MAX_LIMIT)

    def test_khong_tra_ve_person_da_gop(self):
        people = list(Person.objects.all()[:2])
        resolution.merge(people[0], people[1])
        total, _ = search_module.search()
        self.assertEqual(total, 2)

    def test_sap_xep_theo_do_tuoi(self):
        _, rows = search_module.search(order="newest")
        dates = [r.talent_profile.last_source_at for r in rows]
        self.assertEqual(dates, sorted(dates, reverse=True))


class ApiTest(TestCase):
    def setUp(self):
        # Phải có vai trò vào được module Talent (Phase 5B). Người dùng không
        # vai trò bị chặn 403 — có test riêng ở accounts.tests khẳng định điều đó.
        from accounts import roles as role_module
        from django.contrib.auth.models import Group
        role_module.ensure_groups()
        self.user = User.objects.create_user("recruiter", password="mat-khau-rat-dai-1")
        self.user.groups.add(Group.objects.get(name=role_module.RECRUITER))
        self.client.force_login(self.user)
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        data = payload()
        SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key="topcv|ta@msb.com.vn|1", payload=data, content_hash="h1",
            source="topcv", fullname=data["fullname"], email=data["email"],
            phone=data["phone"])
        ingest.resolve_pending()
        self.person = Person.objects.get()

    def test_chua_dang_nhap_thi_bi_chan(self):
        self.client.logout()
        for name, args in (("talent-search", []), ("talent-person", [self.person.pk])):
            self.assertIn(self.client.get(reverse(name, args=args)).status_code,
                          (401, 403))

    def test_tim_kiem_tra_ve_the_ung_vien(self):
        body = self.client.get(reverse("talent-search"), {"q": "An"}).json()
        self.assertEqual(body["count"], 1)
        card = body["results"][0]
        self.assertEqual(card["talent"]["current_title"], "Data Analyst")
        self.assertIn("SQL", card["talent"]["skills"])

    def test_person_360_gom_du_moi_thu(self):
        body = self.client.get(reverse("talent-person", args=[self.person.pk])).json()
        for key in ("identities", "sources", "documents", "document_stats", "timeline", "signals",
                    "relationships", "person_links", "pools", "talent"):
            self.assertIn(key, body)
        self.assertEqual(len(body["identities"]), 2)
        self.assertEqual(len(body["sources"]), 1)

    def test_person_360_hien_quan_he_nguoi_voi_nguoi(self):
        """`PersonLink` từng được tạo mà không hiện ở đâu. Person 360 nay có mục
        `person_links` — người hồ sơ này nhắc tới, và người nhắc tới hồ sơ này."""
        from people.models import PersonLink
        ref = Person.objects.create(display_name="Chị Trần B",
                                    origin=Person.ORIGIN_CV_REFERENCE, is_applicant=False)
        PersonLink.objects.create(subject=self.person, related=ref,
                                  kind=PersonLink.KIND_REFERENCE, confidence=0.9,
                                  evidence={"company": "SeABank"})
        body = self.client.get(reverse("talent-person", args=[self.person.pk])).json()
        out = body["person_links"]["outgoing"]
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["person"]["display_name"], "Chị Trần B")
        self.assertEqual(out[0]["kind"], PersonLink.KIND_REFERENCE)
        self.assertFalse(out[0]["person"]["is_applicant"])
        # phía người tham chiếu thấy chiều ngược lại
        rev = self.client.get(reverse("talent-person", args=[ref.pk])).json()
        self.assertEqual(len(rev["person_links"]["incoming"]), 1)

    def test_loc_theo_nhom_rb_khi_khong_co_module_rb_bi_chan(self):
        """Pool dùng chung bảng cho hai nghiệp vụ: đoán id nhóm khách RB không được
        đọc ra ai đang nằm trong nhóm đó — kể cả qua xuất CSV."""
        rb_pool = Pool.objects.create(name="Khách VIP", domain=Pool.DOMAIN_RB)
        talent_pool = Pool.objects.create(name="Đợt tuyển", domain=Pool.DOMAIN_TALENT)
        for name in ("talent-search", "talent-search-export"):
            self.assertEqual(self.client.get(reverse(name), {"pool": rb_pool.pk}).status_code, 403)
            self.assertEqual(self.client.get(reverse(name), {"pool": talent_pool.pk}).status_code, 200)
        self.assertEqual(self.client.get(reverse("talent-search"), {"pool": 999999}).status_code, 404)

    def test_rm_khong_nhan_cv_nhung_thay_duoc_pipeline_ung_vien(self):
        from accounts import roles as role_module
        from django.contrib.auth.models import Group
        role_module.ensure_groups()
        rm = User.objects.create_user("rm-test", password="mat-khau-rat-dai")
        rm.groups.add(Group.objects.get(name=role_module.RB_SALES))
        self.client.force_login(rm)
        body = self.client.get(reverse("talent-person", args=[self.person.pk])).json()
        self.assertEqual(body["documents"], [])
        self.assertEqual(body["sources"], [])
        self.assertIn("active_worklists", body)

    def test_index_health_an_voi_recruiter(self):
        """Chẩn đoán chỉ mục là chuyện vận hành nội bộ — recruiter không cần
        thấy, tránh nhiễu màn hình Person 360 với thông tin không phải nghiệp
        vụ của họ."""
        body = self.client.get(reverse("talent-person", args=[self.person.pk])).json()
        self.assertNotIn("index_health", body)

    def test_index_health_hien_voi_admin(self):
        from accounts import roles as role_module
        from django.contrib.auth.models import Group
        admin = User.objects.create_user("admin-test", password="mat-khau-rat-dai-1")
        admin.groups.add(Group.objects.get(name=role_module.ADMIN))
        self.client.force_login(admin)
        body = self.client.get(reverse("talent-person", args=[self.person.pk])).json()
        # setUp không đính CV nào — đúng trạng thái "chưa có gì để lập chỉ mục".
        self.assertEqual(body["index_health"]["status"], "no_documents")

    def test_index_health_van_an_voi_edge_operator(self):
        """edge_operator bị chặn hẳn khỏi module Talent (quyết định đã chốt,
        docs/ACCESS_CONTROL.md mục 4.3) — không mở riêng cho chỉ báo này."""
        from accounts import roles as role_module
        from django.contrib.auth.models import Group
        role_module.ensure_groups()
        operator = User.objects.create_user("edge-op-test", password="mat-khau-rat-dai-1")
        operator.groups.add(Group.objects.get(name=role_module.EDGE_OPERATOR))
        self.client.force_login(operator)
        response = self.client.get(reverse("talent-person", args=[self.person.pk]))
        self.assertEqual(response.status_code, 403)

    def test_index_health_phan_anh_du_lieu_chi_muc(self):
        from accounts import roles as role_module
        from django.contrib.auth.models import Group
        from intel.models import ExtractionJob
        from talent.models import CVChunk, PersonSearchDocument
        admin = User.objects.create_user("admin-test-2", password="mat-khau-rat-dai-1")
        admin.groups.add(Group.objects.get(name=role_module.ADMIN))
        self.client.force_login(admin)

        Document.objects.create(person=self.person, sha256="ih1", parse_status="done",
                                parsed_text="Chuyên viên tín dụng. " * 40)
        body = self.client.get(reverse("talent-person", args=[self.person.pk])).json()
        self.assertEqual(body["index_health"]["status"], "missing")
        self.assertFalse(body["index_health"]["has_projection"])

        from talent import vector_index
        vector_index.index_person(self.person.pk, with_embeddings=False)
        body = self.client.get(reverse("talent-person", args=[self.person.pk])).json()
        self.assertEqual(body["index_health"]["status"], "stale")
        self.assertTrue(body["index_health"]["has_projection"])
        self.assertGreater(body["index_health"]["chunks_total"], 0)
        self.assertEqual(body["index_health"]["chunks_current"], 0)

        PersonSearchDocument.objects.filter(person=self.person).update(
            embedding_fingerprint=F("fingerprint"))
        CVChunk.objects.filter(person=self.person).update(
            embedding_fingerprint=F("fingerprint"))
        # setUp đã ingest self.person qua SourceRecord thật — enqueue một
        # ExtractionJob còn treo mà không worker nào trong test xử lý. Đóng nó
        # lại để cô lập đúng thứ test này đang xét (đồng bộ fingerprint), thay
        # vì lẫn với việc trích xuất fact còn dở dang.
        ExtractionJob.objects.filter(person_id=self.person.pk).update(
            status=ExtractionJob.STATUS_DONE)
        body = self.client.get(reverse("talent-person", args=[self.person.pk])).json()
        self.assertEqual(body["index_health"]["status"], "ok")

    def test_xem_ho_so_duoc_ghi_lai_va_khu_trung_lap_trong_ngay(self):
        url = reverse("talent-person", args=[self.person.pk])
        for _ in range(3):
            self.client.get(url)
        viewed = Interaction.objects.filter(person=self.person, action="viewed")
        self.assertEqual(viewed.count(), 1, "timeline không được ngập dòng 'đã xem'")
        self.assertEqual(viewed.first().actor, self.user)

    def test_da_xem_gan_day_chi_tra_ho_so_cua_tai_khoan(self):
        self.client.get(reverse("talent-person", args=[self.person.pk]))
        other = Person.objects.create(display_name="Người khác")
        Interaction.objects.create(person=other, action="viewed")
        body = self.client.get(reverse("talent-recently-viewed")).json()
        self.assertEqual([row["id"] for row in body["results"]], [self.person.pk])

    def test_talent_hien_moi_danh_sach_dang_xu_ly(self):
        from hiring.models import HuntCandidate, HuntRequest
        hunt = HuntRequest.objects.create(title="Data tháng 8", requested_by=self.user,
                                          assigned_to=self.user, status="in_progress")
        HuntCandidate.objects.create(hunt_request=hunt, person=self.person,
                                     assigned_to=self.user, state="contacting")
        card = self.client.get(reverse("talent-search"), {"q": "An"}).json()["results"][0]
        self.assertEqual(card["active_worklists"][0]["title"], "Data tháng 8")
        self.assertEqual(card["active_worklists"][0]["assigned_to_name"], str(self.user))

    def test_person_da_gop_thi_chuyen_huong(self):
        other = Person.objects.create(display_name="Trùng")
        resolution.merge(self.person, other)
        response = self.client.get(reverse("talent-person", args=[other.pk]))
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.json()["redirect_to"], self.person.pk)
        self.assertTrue(response["Location"].endswith(
            f"/api/v1/talent/people/{self.person.pk}/"))

    def test_sua_ho_so_thi_danh_dau_curated(self):
        self.client.patch(
            reverse("talent-profile-update", args=[self.person.pk]),
            data=json.dumps({"current_title": "Trưởng nhóm"}),
            content_type="application/json")
        profile = TalentProfile.objects.get(person=self.person)
        self.assertEqual(profile.current_title, "Trưởng nhóm")
        self.assertIn("current_title", profile.curated_fields)

    def test_nut_suy_lai_khong_xoa_phan_da_sua(self):
        """Nút này không phải nút hoàn tác."""
        self.client.patch(
            reverse("talent-profile-update", args=[self.person.pk]),
            data=json.dumps({"current_title": "Trưởng nhóm"}),
            content_type="application/json")
        self.client.post(reverse("talent-rederive", args=[self.person.pk]))
        self.assertEqual(TalentProfile.objects.get().current_title, "Trưởng nhóm")

    def test_sua_ho_so_duoc_ghi_vao_timeline(self):
        self.client.patch(
            reverse("talent-profile-update", args=[self.person.pk]),
            data=json.dumps({"summary": "Ứng viên tiềm năng"}),
            content_type="application/json")
        self.assertTrue(Interaction.objects.filter(
            person=self.person, action="profile_edited", actor=self.user).exists())

    def test_sua_ho_so_tu_choi_du_lieu_khong_hop_le(self):
        url = reverse("talent-profile-update", args=[self.person.pk])
        for patch in ({"years_experience": -1}, {"years_experience": 81},
                      {"skills": "SQL, Python"}, {"owner_id": 999999}):
            response = self.client.patch(url, data=json.dumps(patch),
                                         content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_facets_phuc_vu_day_du_bo_loc_giao_dien(self):
        body = self.client.get(reverse("talent-facets")).json()
        for key in ("by_source", "by_location", "tags", "pools", "owners",
                    "relationships", "products", "lead_statuses"):
            self.assertIn(key, body)

    def test_cap_nhat_quan_he_ung_vien_dai_han(self):
        response = self.client.patch(
            reverse("talent-relationship", args=[self.person.pk]),
            data=json.dumps({
                "state": "nurturing", "owner_id": self.user.pk,
                "interest_level": 4, "preferred_channel": "zalo",
                "next_action": "Hỏi lại sau kỳ nghỉ",
                "next_action_at": (timezone.now() + timezone.timedelta(days=2)).isoformat(),
                "preferences": {"preferred_roles": "Data Lead", "work_mode": "hybrid"},
            }), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        relation = Relationship.objects.get(person=self.person, domain="talent")
        self.assertEqual(relation.owner_user, self.user)
        self.assertEqual(relation.state, "nurturing")
        self.assertEqual(relation.interest_level, 4)
        self.assertEqual(relation.preferences["preferred_roles"], "Data Lead")

    def test_quan_he_tu_choi_trang_thai_va_muc_quan_tam_sai(self):
        url = reverse("talent-relationship", args=[self.person.pk])
        for patch in ({"state": "submitted"}, {"interest_level": 6}):
            response = self.client.patch(
                url, data=json.dumps(patch), content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_danh_sach_quan_he_den_han_chi_hien_cua_toi_va_khong_DNC(self):
        due = timezone.now() - timezone.timedelta(hours=1)
        Relationship.objects.create(
            person=self.person, domain="talent", state="nurturing",
            owner_user=self.user, next_action="Gọi lại", next_action_at=due)
        body = self.client.get(reverse("talent-relationship-followups")).json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["relationship_followup"]["next_action"],
                         "Gọi lại")

        relation = Relationship.objects.get(person=self.person, domain="talent")
        relation.do_not_contact = True
        relation.save()
        self.assertEqual(
            self.client.get(reverse("talent-relationship-followups")).json()["count"], 0)

    def test_text_cv_chi_tai_khi_yeu_cau(self):
        document = Document.objects.create(
            person=self.person, filename="cv.pdf", sha256="a" * 64,
            parsed_text="Nội dung CV", text_length=11, parse_status="done")
        detail = self.client.get(reverse("talent-person", args=[self.person.pk])).json()
        self.assertNotIn("parsed_text", detail["documents"][0])
        body = self.client.get(reverse("talent-document-text", args=[document.pk])).json()
        self.assertEqual(body["text"], "Nội dung CV")

    def test_thong_ke_kho_cv_phan_biet_luot_nop_file_va_text_trung(self):
        from people.parsed_text import save_parsed_text

        records = list(self.person.source_records.all())
        second_record = SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record", entity_key="topcv|ta@msb.com.vn|2",
            payload={"applied_ts": "2026-08-20"}, content_hash="h2", source="topcv",
            fullname=self.person.display_name, person=self.person)
        records.append(second_record)
        for index, record in enumerate(records):
            document = Document.objects.create(
                person=self.person, filename=f"cv-{index}.pdf", sha256=str(index + 1) * 64)
            document.source_records.add(record)
            save_parsed_text(document, "Python và SQL", origin="edge", quality_score=0.8)
        stats = self.client.get(
            reverse("talent-person", args=[self.person.pk])).json()["document_stats"]
        self.assertEqual(stats["submission_count"], 2)
        self.assertEqual(stats["file_version_count"], 2)
        self.assertEqual(stats["distinct_text_count"], 1)
        self.assertEqual(stats["duplicate_text_count"], 1)

    # ---------- nhãn ----------

    def test_tao_va_gan_nhan(self):
        self.client.post(reverse("talent-tags"),
                         data=json.dumps({"name": "Ưu tiên cao"}),
                         content_type="application/json")
        tag = Tag.objects.get()
        self.assertEqual(tag.slug, "uu-tien-cao")

        self.client.post(reverse("talent-person-tags", args=[self.person.pk]),
                         data=json.dumps({"tag": tag.slug}),
                         content_type="application/json")
        self.assertEqual(TalentProfile.objects.get().tags.count(), 1)

    def test_go_nhan(self):
        tag = Tag.objects.create(name="Tạm")
        TalentProfile.objects.get(person=self.person).tags.add(tag)
        self.client.delete(reverse("talent-person-tags", args=[self.person.pk]),
                           data=json.dumps({"tag": tag.slug}),
                           content_type="application/json")
        self.assertEqual(TalentProfile.objects.get().tags.count(), 0)

    def test_nhan_khong_ton_tai_thi_404(self):
        response = self.client.post(
            reverse("talent-person-tags", args=[self.person.pk]),
            data=json.dumps({"tag": "khong-co"}), content_type="application/json")
        self.assertEqual(response.status_code, 404)

    def test_loc_theo_nhan(self):
        tag = Tag.objects.create(name="Ưu tiên")
        TalentProfile.objects.get(person=self.person).tags.add(tag)
        total, _ = search_module.search(tags=[tag.slug])
        self.assertEqual(total, 1)

    # ---------- pool ----------

    def test_tao_pool_va_them_thanh_vien(self):
        response = self.client.post(reverse("talent-pools"),
                                    data=json.dumps({"name": "Data Q4/2026"}),
                                    content_type="application/json")
        pool_id = response.json()["id"]
        self.client.post(reverse("talent-pool-members", args=[pool_id]),
                         data=json.dumps({"person_id": self.person.pk}),
                         content_type="application/json")
        pool = Pool.objects.get()
        self.assertEqual(pool.memberships.count(), 1)
        self.assertEqual(pool.owner, self.user)
        self.assertEqual(pool.domain, Pool.DOMAIN_TALENT)

    def test_recruiter_khong_doc_duoc_nhom_khach_hang(self):
        Pool.objects.create(name="Khách ưu tiên", domain=Pool.DOMAIN_RB)
        response = self.client.get(reverse("talent-pools"), {"domain": "rb"})
        self.assertEqual(response.status_code, 403)

    def test_them_hai_lan_khong_tao_ban_ghi_trung(self):
        pool = Pool.objects.create(name="P")
        for _ in range(2):
            self.client.post(reverse("talent-pool-members", args=[pool.pk]),
                             data=json.dumps({"person_id": self.person.pk}),
                             content_type="application/json")
        self.assertEqual(PoolMembership.objects.count(), 1)

    def test_pool_ghi_lai_ai_them_luc_nao(self):
        pool = Pool.objects.create(name="P")
        self.client.post(reverse("talent-pool-members", args=[pool.pk]),
                         data=json.dumps({"person_id": self.person.pk}),
                         content_type="application/json")
        membership = PoolMembership.objects.get()
        self.assertEqual(membership.added_by, self.user)
        self.assertEqual(membership.added_by_name, "recruiter")

    def test_xem_thanh_vien_pool_de_dua_vao_xu_ly(self):
        pool = Pool.objects.create(name="Data team", owner=self.user)
        PoolMembership.objects.create(pool=pool, person=self.person,
                                      added_by=self.user)
        response = self.client.get(reverse("talent-pool-members", args=[pool.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pool"]["name"], "Data team")
        self.assertEqual(response.json()["results"][0]["id"], self.person.pk)

    def test_xoa_khoi_pool(self):
        pool = Pool.objects.create(name="P")
        PoolMembership.objects.create(pool=pool, person=self.person)
        self.client.delete(reverse("talent-pool-members", args=[pool.pk]),
                           data=json.dumps({"person_id": self.person.pk}),
                           content_type="application/json")
        self.assertEqual(PoolMembership.objects.count(), 0)

    def test_loc_theo_pool(self):
        pool = Pool.objects.create(name="P")
        PoolMembership.objects.create(pool=pool, person=self.person)
        total, _ = search_module.search(pool=pool)
        self.assertEqual(total, 1)


class OwnerTest(TestCase):
    def test_xoa_tai_khoan_khong_lam_mat_ho_so(self):
        """Recruiter nghỉ việc, hồ sơ ứng viên vẫn phải còn."""
        user = User.objects.create_user("r1", password="mat-khau-rat-dai-1")
        person = Person.objects.create(display_name="X")
        profile = TalentProfile.objects.create(person=person, owner=user)
        self.assertEqual(profile.owner_name, "r1")

        user.delete()
        profile.refresh_from_db()
        self.assertIsNone(profile.owner_id)
        self.assertEqual(profile.owner_name, "r1")


class SearchExportTest(TestCase):
    """Xuất CSV (Master Plan mục 15) — phải khớp đúng bộ lọc đang xem, không
    phải một phiên bản gần giống."""

    def setUp(self):
        from accounts import roles as role_module
        from django.contrib.auth.models import Group
        role_module.ensure_groups()
        self.user = User.objects.create_user("recruiter2", password="mat-khau-rat-dai-1")
        self.user.groups.add(Group.objects.get(name=role_module.RECRUITER))
        self.client.force_login(self.user)

        edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        for ten, chuc_danh, ky_nang in (("An", "Data Analyst", "SQL, Python"),
                                        ("Bình", "Backend Engineer", "Java")):
            SourceRecord.objects.create(
                edge=edge, entity_type="source_record",
                entity_key=f"topcv|a|{ten}", content_hash=f"h{ten}",
                payload={"source": "topcv", "fullname": f"Nguyễn Văn {ten}",
                         "email": f"{ten}@x.vn", "current_title": chuc_danh,
                         "position": chuc_danh, "skills": ky_nang,
                         "applied_ts": "2026-08-01 09:00:00"})
        ingest.resolve_pending()

    def test_xuat_ra_dung_CSV(self):
        response = self.client.get(reverse("talent-search-export"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        text = response.content.decode("utf-8-sig")
        self.assertIn("Nguyễn Văn An", text)
        self.assertIn("Nguyễn Văn Bình", text)

    def test_loc_thi_XUAT_dung_nhung_nguoi_da_loc(self):
        """File tải về phải khớp đúng bộ lọc đang xem — không xuất cả bảng."""
        response = self.client.get(reverse("talent-search-export"), {"skills": "SQL"})
        text = response.content.decode("utf-8-sig")
        self.assertIn("Nguyễn Văn An", text)
        self.assertNotIn("Nguyễn Văn Bình", text)

    def test_co_dong_tieu_de_tieng_Viet(self):
        response = self.client.get(reverse("talent-search-export"))
        text = response.content.decode("utf-8-sig")
        first_line = text.splitlines()[0]
        self.assertIn("Họ tên", first_line)
        self.assertIn("Chức danh", first_line)

    def test_co_BOM_de_Excel_doc_dung_UTF8(self):
        response = self.client.get(reverse("talent-search-export"))
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))

    def test_chua_dang_nhap_bi_chan(self):
        self.client.logout()
        self.assertIn(self.client.get(reverse("talent-search-export")).status_code,
                      (401, 403))
