# -*- coding: utf-8 -*-
"""Kiểm thử tách liên hệ ứng viên khỏi liên hệ người tham chiếu.

Hai kiểu sai nguy hiểm nhất ở đây:
  1. Gán email người tham chiếu làm ĐỊNH DANH của ứng viên — hai ứng viên cùng
     một người tham chiếu sẽ bị gộp thành một Person.
  2. Nhận một email/SĐT model tự bịa ra — dữ liệu bẩn không lần ra được nguồn.
"""
import json
from types import SimpleNamespace

from django.test import TestCase
from people.models import ContactMention, Person, PersonLink

from . import contacts


def _adapter(payload):
    """Adapter giả trả đúng JSON cho trước — không gọi mạng."""
    class _Fake:
        def complete(self, request):
            return SimpleNamespace(
                text=json.dumps(payload, ensure_ascii=False),
                model="fake-1",
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20))
    return _Fake()


CV = """
NGUYỄN HẢI YẾN
Email: nguyenvanan105@gmail.com — Điện thoại: 0912345678

NGƯỜI THAM CHIẾU
Chị Trần B — Trưởng phòng KHCN, SeABank — nguoi.tham.chieu@seabank.com.vn — 0987654321
"""


class CoGoiAITest(TestCase):
    def test_chi_goi_ai_khi_cv_co_dau_hieu_muc_tham_chieu(self):
        self.assertTrue(contacts.has_reference_markers(CV))
        self.assertTrue(contacts.has_reference_markers("REFERENCES: John Doe"))
        self.assertTrue(contacts.has_reference_markers("Nguoi tham chieu: A"))
        # CV thường không có mục này — gọi AI cho mọi hồ sơ là tốn tiền để nhận
        # về danh sách rỗng (cùng kỷ luật với core/cv_parsing.can_ai_chuan_hoa).
        self.assertFalse(contacts.has_reference_markers(
            "Kinh nghiệm: 5 năm bán hàng. Kỹ năng: Excel, giao tiếp."))


class BocLienHeTest(TestCase):
    def test_tach_dung_lien_he_ung_vien_va_nguoi_tham_chieu(self):
        got, usage = contacts.extract_contacts(CV, "Nguyễn Văn An", _adapter({
            "candidate": {"emails": ["nguyenvanan105@gmail.com"],
                          "phones": ["0912345678"]},
            "references": [{"full_name": "Trần B", "title": "Trưởng phòng KHCN",
                            "company": "SeABank", "email": "nguoi.tham.chieu@seabank.com.vn",
                            "phone": "0987654321", "kind": "reference",
                            "evidence": "NGƯỜI THAM CHIẾU: Chị Trần B",
                            "confidence": 0.9}]}))
        self.assertEqual(got["candidate"]["emails"], ["nguyenvanan105@gmail.com"])
        self.assertEqual(len(got["references"]), 1)
        self.assertEqual(got["references"][0]["company"], "SeABank")
        self.assertEqual(got["references"][0]["kind"], ContactMention.KIND_REFERENCE)
        self.assertEqual(usage["model"], "fake-1")

    def test_email_model_BIA_RA_bi_loai(self):
        """Chốt chặn quan trọng nhất: chỉ nhận giá trị có NGUYÊN VĂN trong CV."""
        got, _ = contacts.extract_contacts(CV, "Nguyễn Văn An", _adapter({
            "candidate": {"emails": ["khongcotrongcv@gmail.com"], "phones": []},
            "references": [{"full_name": "Ma", "email": "bia@dat.ra",
                            "phone": "0900000000", "evidence": "x"}]}))
        self.assertEqual(got["candidate"]["emails"], [])
        self.assertEqual(got["references"], [])

    def test_so_dien_thoai_viet_cach_khac_van_duoc_nhan(self):
        """CV viết '0912 345 678' hay '(+84) 912.345.678' đều là cùng một số."""
        got, _ = contacts.extract_contacts(
            "Lien he: 0912 345 678\nNGUOI THAM CHIEU: A - a@x.com",
            "", _adapter({"candidate": {"phones": ["0912345678"], "emails": []},
                          "references": []}))
        self.assertEqual(got["candidate"]["phones"], ["0912345678"])

    def test_nguoi_duoc_nhac_ma_khong_co_cach_lien_he_thi_bo(self):
        got, _ = contacts.extract_contacts(CV, "", _adapter({
            "candidate": {"emails": [], "phones": []},
            "references": [{"full_name": "Ai Đó", "company": "X", "evidence": "y"}]}))
        self.assertEqual(got["references"], [])

    def test_json_hong_bao_ra_ngoai_chu_khong_im_lang_tra_rong(self):
        class _Broken:
            def complete(self, request):
                return SimpleNamespace(text="{cụt giữa chừng", model="fake-1",
                                       usage=SimpleNamespace(prompt_tokens=1,
                                                             completion_tokens=2))
        got, usage = contacts.extract_contacts(CV, "", _Broken())
        self.assertEqual(got, {})
        self.assertTrue(usage["parse_failed"])


class GhiVaThangHangTest(TestCase):
    def setUp(self):
        self.candidate = Person.objects.create(
            display_name="Nguyễn Văn An", primary_email="nguyenvanan105@gmail.com")
        self.extracted = {"references": [{
            "full_name": "Trần B", "title": "Trưởng phòng KHCN", "company": "SeABank",
            "relationship": "quản lý cũ", "email_raw": "nguoi.tham.chieu@seabank.com.vn",
            "phone_raw": "0987654321", "kind": ContactMention.KIND_REFERENCE,
            "evidence": "NGƯỜI THAM CHIẾU: Chị Trần B", "confidence": 0.9}]}

    def test_ghi_ContactMention_khong_tao_person_ngay(self):
        saved = contacts.record_mentions(self.candidate, None, self.extracted)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].email, "nguoi.tham.chieu@seabank.com.vn")
        self.assertEqual(saved[0].phone, "+84987654321")
        self.assertEqual(saved[0].status, ContactMention.STATUS_PROPOSED)
        self.assertIsNone(saved[0].linked_person)
        self.assertEqual(Person.objects.count(), 1)   # chưa tạo người thứ hai

    def test_chay_lai_tren_cung_mot_cv_khong_de_them_ban_ghi_trung(self):
        contacts.record_mentions(self.candidate, None, self.extracted)
        contacts.record_mentions(self.candidate, None, self.extracted)
        self.assertEqual(ContactMention.objects.count(), 1)

    def test_thang_hang_tao_person_co_nhan_rieng_va_quan_he(self):
        mention = contacts.record_mentions(self.candidate, None, self.extracted)[0]
        person = contacts.promote(mention)

        self.assertIsNotNone(person)
        self.assertNotEqual(person.pk, self.candidate.pk)
        self.assertEqual(person.origin, Person.ORIGIN_CV_REFERENCE)
        # Chưa từng ứng tuyển -> không được đếm vào pool ứng viên.
        self.assertFalse(person.is_applicant)
        self.assertNotIn(person.pk, set(Person.applicants().values_list("pk", flat=True)))

        link = PersonLink.objects.get(subject=self.candidate, related=person)
        self.assertEqual(link.kind, PersonLink.KIND_REFERENCE)
        self.assertEqual(link.evidence["company"], "SeABank")

        mention.refresh_from_db()
        self.assertEqual(mention.status, ContactMention.STATUS_ACCEPTED)
        self.assertEqual(mention.linked_person_id, person.pk)

    def test_nguoi_tham_chieu_ve_sau_tu_ung_tuyen_thi_gop_ve_dung_mot_nguoi(self):
        """Lợi ích của việc dùng lại `resolution.resolve()`: trùng email thì
        khớp vào Person đang có, lịch sử quan hệ còn nguyên."""
        from people import resolution

        mention = contacts.record_mentions(self.candidate, None, self.extracted)[0]
        ref = contacts.promote(mention)

        result = resolution.resolve({
            "source": "topcv", "cv_id": "9", "fullname": "Phạm Thị Thuỳ",
            "email": "nguoi.tham.chieu@seabank.com.vn", "phone": "0987654321"})
        self.assertEqual(result.outcome, resolution.MATCHED)
        self.assertEqual(result.person.pk, ref.pk)
        result.person.refresh_from_db()
        # Nay họ đã ứng tuyển -> vào pool ứng viên, nhưng `origin` giữ nguyên
        # vì "biết đến qua đâu" là chuyện của quá khứ.
        self.assertTrue(result.person.is_applicant)
        self.assertEqual(result.person.origin, Person.ORIGIN_CV_REFERENCE)
        self.assertEqual(PersonLink.objects.filter(related=ref).count(), 1)

    def test_khong_tao_quan_he_tu_tro_ve_chinh_minh(self):
        """CV ghi lại chính email của ứng viên trong mục tham chiếu."""
        mention = contacts.record_mentions(self.candidate, None, {"references": [{
            "full_name": "Nguyễn Văn An", "email_raw": "nguyenvanan105@gmail.com",
            "phone_raw": "", "kind": ContactMention.KIND_REFERENCE,
            "evidence": "x", "confidence": 0.5}]})[0]
        # Person của ứng viên chưa có Identity nên resolve() tạo người mới;
        # điều cần khẳng định là không sinh ra quan hệ tự trỏ.
        person = contacts.promote(mention)
        self.assertFalse(PersonLink.objects.filter(subject=person, related=person).exists())

    def test_thang_hang_tao_tin_hieu_ban_hang_co_provenance(self):
        """Người tham chiếu là banker ngân hàng khác — nguồn khách hàng tiềm
        năng. Đi qua `Signal(domain=rb)` để được luôn chuỗi chấm điểm/phân RM
        của `rb/`, và để nhìn evidence là biết cơ hội đến từ CV của ai."""
        from people.models import Signal

        mention = contacts.record_mentions(self.candidate, None, self.extracted)[0]
        person = contacts.promote(mention)
        signal = Signal.objects.get(person=person, signal_type="cv_reference")
        self.assertEqual(signal.domain, Signal.DOMAIN_RB)
        self.assertEqual(signal.evidence["company"], "SeABank")
        self.assertEqual(signal.evidence["gioi_thieu_boi_person_id"], self.candidate.pk)

    def test_chi_tu_thang_hang_khi_do_tin_du_cao(self):
        """Thăng hạng = tạo một CON NGƯỜI mới trong kho. Model không chắc thì để
        lại `proposed` cho người xem, đừng làm bẩn dữ liệu của cả hai nghiệp vụ."""
        thap = {"references": [dict(self.extracted["references"][0],
                                    email_raw="mo.ho@vpbank.com.vn", confidence=0.4)]}
        saved = contacts.record_mentions(self.candidate, None, thap)
        self.assertEqual(contacts.promote_confident(saved), 0)
        saved[0].refresh_from_db()
        self.assertEqual(saved[0].status, ContactMention.STATUS_PROPOSED)
        self.assertIsNone(saved[0].linked_person)

        cao = contacts.record_mentions(self.candidate, None, self.extracted)
        self.assertEqual(contacts.promote_confident(cao), 1)
        self.assertEqual(PersonLink.objects.count(), 1)

    def test_lien_he_cua_chinh_ung_vien_khong_sinh_quan_he(self):
        mention = contacts.record_mentions(self.candidate, None, {"references": [{
            "full_name": "", "email_raw": "nguyenvanan105@gmail.com", "phone_raw": "",
            "kind": ContactMention.KIND_SELF, "evidence": "x", "confidence": 0.9}]})[0]
        self.assertIsNone(contacts.promote(mention))
        self.assertEqual(PersonLink.objects.count(), 0)


class VotLienHeTuOGopTest(TestCase):
    """Đường AI text chỉ bắt người tham chiếu khi CV có tiêu đề rõ. Người giới
    thiệu ghi chen ngang một dòng thì lọt — nhưng Edge vẫn vớt email/SĐT họ vào
    `cv_emails`/`cv_phones`. Không được để mất."""

    def setUp(self):
        from core.models import Edge, SourceRecord
        self.person = Person.objects.create(
            display_name="Nguyễn Văn An", primary_email="nguyenvanan105@gmail.com")
        edge = Edge.objects.create(label="M", edge_id="e1")
        self.record = SourceRecord.objects.create(
            edge=edge, entity_type="source_record", entity_key="topcv|a|1",
            content_hash="h1", person=self.person,
            payload={"source": "topcv", "fullname": "Nguyễn Văn An",
                     "email": "nguyenvanan105@gmail.com", "phone": "0912345678",
                     "cv_emails": ["nguyenvanan105@gmail.com", "nguoi.tham.chieu@seabank.com.vn"],
                     "cv_phones": ["0912345678", "0987654321"]})

    def test_ghi_phan_du_diem_tin_thap_khong_tu_thang_hang(self):
        saved = contacts.record_blob_contacts(self.person, [self.record])
        vals = {(m.email, m.phone) for m in saved}
        self.assertIn(("nguoi.tham.chieu@seabank.com.vn", ""), vals)
        self.assertIn(("", "+84987654321"), vals)
        # liên hệ của chính ứng viên KHÔNG bị ghi
        self.assertNotIn(("nguyenvanan105@gmail.com", ""), vals)
        for m in saved:
            self.assertLess(m.confidence, contacts.AUTO_PROMOTE_GATE)
            self.assertEqual(m.extractor, contacts.EXTRACTOR_BLOB)
            self.assertEqual(m.status, ContactMention.STATUS_PROPOSED)
        self.assertEqual(contacts.promote_confident(saved), 0)

    def test_khong_de_len_ban_ghi_duong_AI_text_da_co(self):
        contacts.record_mentions(self.person, None, {"references": [{
            "full_name": "Trần B", "title": "Trưởng phòng", "company": "SeABank",
            "email_raw": "nguoi.tham.chieu@seabank.com.vn", "phone_raw": "",
            "kind": ContactMention.KIND_REFERENCE, "evidence": "NGƯỜI THAM CHIẾU",
            "confidence": 0.9}]})
        contacts.record_blob_contacts(self.person, [self.record])
        row = ContactMention.objects.get(email="nguoi.tham.chieu@seabank.com.vn")
        self.assertEqual(row.extractor, contacts.EXTRACTOR)   # bản AI được giữ
        self.assertEqual(row.company, "SeABank")

    def test_chay_lai_khong_de_them_ban_ghi_trung(self):
        contacts.record_blob_contacts(self.person, [self.record])
        contacts.record_blob_contacts(self.person, [self.record])
        self.assertEqual(
            ContactMention.objects.filter(extractor=contacts.EXTRACTOR_BLOB).count(), 2)
