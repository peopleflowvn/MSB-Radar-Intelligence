# -*- coding: utf-8 -*-
"""Kiểm thử People Core.

Trọng tâm là những cách hệ thống có thể GỘP NHẦM HAI NGƯỜI. Đó là sai lầm gần
như không gỡ lại được của toàn bộ dự án: hồ sơ trộn lẫn, recruiter gọi nhầm
người. Tách nhầm thì chỉ phiền, gộp lại được bất cứ lúc nào.
"""
from django.test import TestCase
from django.db.models import F
from django.utils import timezone

from core.models import Edge, SourceRecord

from . import ingest, resolution
from .models import (Document, Identity, IdentityConflict, Interaction, Opportunity,
                     Person, Relationship, Signal)
from .normalize import (choose_primary_email, dedupe_emails, email_matches_name,
                        normalize_email, normalize_name, normalize_phone,
                        normalize_provider_person_id, normalize_url_identity,
                        split_contacts, split_emails)


def payload(**overrides):
    data = {
        "source": "topcv", "account": "ta@msb.com.vn", "cv_id": "1",
        "fullname": "Nguyễn Văn An", "email": "an.nguyen@example.com",
        "phone": "0901234567", "position": "Data Analyst", "city": "Hà Nội",
    }
    data.update(overrides)
    return data


class OLienHeNhieuGiaTriTest(TestCase):
    """Edge gộp MỌI email/điện thoại bóc từ CV vào một ô.

    Trước khi có lớp tách này, `normalize_email("a@x.com, b@y.com")` trả rỗng
    nên Hub im lặng vứt cả định danh. Đo trên 283 hồ sơ thật: 28 mất email,
    32 mất điện thoại, 5 hồ sơ mất cả hai và không tạo được Person nào.
    """

    def test_tach_theo_dau_phan_cach_nhung_khong_tach_so_dien_thoai_co_dau_cach(self):
        self.assertEqual(split_contacts("0901234567, 0912345678"),
                         ["0901234567", "0912345678"])
        # "090 123 4567" là MỘT số, không phải ba mẩu.
        self.assertEqual(split_contacts("090 123 4567"), ["090 123 4567"])

    def test_email_tach_duoc_ca_theo_khoang_trang(self):
        self.assertEqual(split_emails("a@x.com b@y.com"), ["a@x.com", "b@y.com"])

    def test_email_bi_cat_cut_duoc_gop_vao_ban_day_du(self):
        """Bộ trích PDF trả cùng một địa chỉ hai lần, một bản thiếu ký tự cuối.
        Quan sát thật trên hồ sơ 'Nguyễn Ngọc Bích'."""
        self.assertEqual(
            dedupe_emails(["lethib16042004@gmail.com",
                           "lethib16042004@gmail.co"]),
            ["lethib16042004@gmail.com"])

    def test_hai_email_khac_nhau_mot_ky_tu_KHONG_bi_gop(self):
        """`an1@` và `an2@` chỉ khác một ký tự mà là hai người thật — gộp theo
        khoảng cách sửa là chỗ sinh lỗi gộp nhầm, nên cố ý không làm."""
        self.assertEqual(len(dedupe_emails(["an1@gmail.com", "an2@gmail.com"])), 2)
        self.assertEqual(
            len(dedupe_emails(["huyenane.147@gmail.com", "huyenanhle.147@gmail.com"])), 2)

    def test_khop_ten_nhan_ra_email_cua_chinh_ung_vien(self):
        self.assertTrue(email_matches_name("nguyenvanan105@gmail.com", "Nguyễn Văn An"))
        self.assertFalse(email_matches_name("nguoi.tham.chieu@seabank.com.vn", "Nguyễn Văn An"))

    def test_chon_dung_email_ung_vien_giua_email_nguoi_tham_chieu(self):
        """Ca thật: CV kèm email hai banker ngân hàng khác làm người tham chiếu."""
        email, guessed = choose_primary_email(
            ["nguyenvanan105@gmail.com", "nguoi.tham.chieu@seabank.com.vn",
             "tham.chieu.2@vpbank.com.vn"], "Nguyễn Văn An")
        self.assertEqual(email, "nguyenvanan105@gmail.com")
        self.assertFalse(guessed)

    def test_mot_email_ca_nhan_giua_email_cong_ty_van_la_tin_hieu_chac(self):
        """Email công ty trong CV hầu hết là của người tham chiếu, nên khi chỉ
        có đúng một hộp thư cá nhân thì đó là ứng viên — không phải phỏng đoán."""
        email, guessed = choose_primary_email(
            ["thotl@gmail.com", "tri.nch@ncb-bank.vn"], "Không Liên Quan")
        self.assertEqual(email, "thotl@gmail.com")
        self.assertFalse(guessed)

    def test_nhieu_hop_thu_ca_nhan_ma_khong_cai_nao_khop_ten_thi_la_doan(self):
        """Ca thật của 'Thảo Huỳnh Thị Phương': hai gmail + một email NCB."""
        _, guessed = choose_primary_email(
            ["thaohtp107@gmail.com", "tri.nch@ncb-bank.vn", "thotl@gmail.com"],
            "Thảo Huỳnh Thị Phương")
        self.assertTrue(guessed)

    def test_o_gop_nhieu_gia_tri_van_rut_duoc_dinh_danh(self):
        ids = resolution.extract_identities(payload(
            email="nguyenvanan105@gmail.com, nguoi.tham.chieu@seabank.com.vn",
            phone="0912345678, 0987654321", fullname="Nguyễn Văn An"))
        kinds = [kind for kind, _, _ in ids]
        self.assertIn(Identity.KIND_EMAIL, kinds)
        self.assertIn(Identity.KIND_PHONE, kinds)

    def test_chi_gan_MOT_dinh_danh_moi_loai(self):
        """Gắn tất cả email trong ô là cách chắc chắn nhất để gộp nhầm: hai ứng
        viên cùng ghi một người tham chiếu sẽ dính vào chung một Person."""
        ids = resolution.extract_identities(payload(
            email="a@gmail.com, b@seabank.com.vn, c@vpbank.com.vn",
            phone="0912345678, 0987654321, 0986939680"))
        kinds = [kind for kind, _, _ in ids]
        self.assertEqual(kinds.count(Identity.KIND_EMAIL), 1)
        self.assertEqual(kinds.count(Identity.KIND_PHONE), 1)

    def test_hai_ung_vien_chung_mot_nguoi_tham_chieu_KHONG_bi_gop(self):
        first = resolution.resolve(payload(
            cv_id="1", fullname="Nguyễn Văn An",
            email="nguyenvanan105@gmail.com, nguoi.tham.chieu@seabank.com.vn",
            phone="0912345678"))
        second = resolution.resolve(payload(
            cv_id="2", fullname="Nguyễn Hữu Thành",
            email="nguyenvanc28392@gmail.com, nguoi.tham.chieu@seabank.com.vn",
            phone="0947445205"))
        self.assertEqual(first.outcome, resolution.CREATED)
        self.assertEqual(second.outcome, resolution.CREATED)
        self.assertNotEqual(first.person.pk, second.person.pk)

    def test_lien_he_du_di_sang_tang_bang_chung_khong_tu_gan(self):
        pool = resolution.contact_pool(payload(
            fullname="Nguyễn Văn An",
            email="nguyenvanan105@gmail.com, nguoi.tham.chieu@seabank.com.vn",
            phone="0912345678, 0987654321"))
        self.assertEqual(pool["primary_email"], "nguyenvanan105@gmail.com")
        self.assertEqual(pool["extra_emails"], ["nguoi.tham.chieu@seabank.com.vn"])
        self.assertEqual(pool["extra_phones"], ["+84987654321"])

    def test_cv_emails_cua_edge_moi_duoc_doc_ca_dang_list_lan_chuoi_json(self):
        for value in (["b@seabank.com.vn"], '["b@seabank.com.vn"]'):
            pool = resolution.contact_pool(payload(
                fullname="Nguyễn Văn An", email="nguyenvanan105@gmail.com",
                cv_emails=value))
            self.assertEqual(pool["extra_emails"], ["b@seabank.com.vn"],
                             f"lỗi với {value!r}")

    def test_nhieu_so_dien_thoai_KHONG_bat_co_soat_tay(self):
        """Người có hai số là chuyện thường. Bật cờ cho cả nhóm đó thì 13% kho
        vào hàng đợi review và người dùng ngừng đọc cờ — mất tác dụng cảnh báo."""
        person = resolution.resolve(payload(phone="0901234567, 0912345678")).person
        self.assertFalse(person.needs_review)

    def test_khong_biet_email_cua_ai_thi_bat_co_soat_tay(self):
        person = resolution.resolve(payload(
            fullname="Thảo Huỳnh Thị Phương",
            email="thaohtp107@gmail.com, tri.nch@ncb-bank.vn, thotl@gmail.com")).person
        self.assertTrue(person.needs_review)


class PhoneNormalizeTest(TestCase):
    def test_cac_cach_viet_cua_cung_mot_so_cho_cung_ket_qua(self):
        """Đây chính là chênh lệch giữa Edge (bỏ dấu phân cách) và Master Plan (E.164)."""
        for raw in ("0901234567", "090 123 4567", "090-123-4567", "+84901234567",
                    "84901234567", "0084901234567", "(090) 123.4567"):
            self.assertEqual(normalize_phone(raw), "+84901234567", f"lỗi với {raw!r}")

    def test_quy_doi_dau_so_11_so_cu(self):
        """CV cũ trong kho còn số trước lần đổi đầu số 2018."""
        self.assertEqual(normalize_phone("01626543210"), normalize_phone("0326543210"))
        self.assertEqual(normalize_phone("01216543210"), normalize_phone("0796543210"))

    def test_so_co_dinh_bi_loai(self):
        """Số tổng đài công ty dùng chung cho cả phòng — lấy làm định danh sẽ gộp nhầm."""
        for raw in ("02439998888", "0243 999 8888", "024 3999 8888"):
            self.assertEqual(normalize_phone(raw), "", f"phải loại {raw!r}")

    def test_so_khong_hop_le_bi_loai(self):
        for raw in ("", None, "khong phai so", "090", "09012345678901234", "0000000000"):
            self.assertEqual(normalize_phone(raw), "")

    def test_so_nuoc_ngoai_co_dau_cong_duoc_giu(self):
        self.assertEqual(normalize_phone("+6591234567"), "+6591234567")
        self.assertEqual(normalize_phone("+1 415 555 0100"), "+14155550100")

    def test_dau_so_khong_ton_tai_bi_loai(self):
        self.assertEqual(normalize_phone("0111234567"), "")


class EmailNormalizeTest(TestCase):
    def test_ha_chu_thuong_va_cat_khoang_trang(self):
        self.assertEqual(normalize_email("  An.Nguyen@Example.COM "), "an.nguyen@example.com")

    def test_khong_bo_dau_cham_hay_tag(self):
        """Quy tắc bỏ dấu chấm chỉ đúng với Gmail; áp cho tên miền doanh nghiệp sẽ gộp nhầm."""
        self.assertNotEqual(normalize_email("a.n@msb.com.vn"), normalize_email("an@msb.com.vn"))
        self.assertNotEqual(normalize_email("an+cv@msb.com.vn"), normalize_email("an@msb.com.vn"))

    def test_email_sai_dinh_dang_bi_loai(self):
        for raw in ("", None, "khongcoa", "a@b", "a@@b.com", "a b@c.com", "@example.com"):
            self.assertEqual(normalize_email(raw), "")


class NameNormalizeTest(TestCase):
    def test_bo_dau_tieng_viet(self):
        self.assertEqual(normalize_name("Nguyễn Văn An"), "nguyen van an")
        self.assertEqual(normalize_name("Đỗ Thị Hà"), "do thi ha")

    def test_gop_khoang_trang_va_ha_chu_thuong(self):
        self.assertEqual(normalize_name("  TRẦN   BÌNH  "), "tran binh")


class ProviderIdNormalizeTest(TestCase):
    def test_khoa_kem_ten_nguon(self):
        """candidate_id 12345 của TopCV và của VietnamWorks là hai người khác nhau."""
        self.assertNotEqual(normalize_provider_person_id("topcv", "12345"),
                            normalize_provider_person_id("vietnamworks", "12345"))

    def test_thieu_thanh_phan_thi_rong(self):
        self.assertEqual(normalize_provider_person_id("topcv", ""), "")
        self.assertEqual(normalize_provider_person_id("", "12345"), "")


class UrlIdentityNormalizeTest(TestCase):
    def test_cac_bien_the_url_cho_cung_khoa(self):
        for raw in ("https://www.linkedin.com/in/an-nguyen/",
                    "http://linkedin.com/in/an-nguyen",
                    "linkedin.com/in/an-nguyen?utm_source=cv"):
            self.assertEqual(normalize_url_identity(raw), "linkedin.com/in/an-nguyen")

    def test_url_khong_co_duong_dan_bi_loai(self):
        self.assertEqual(normalize_url_identity("https://linkedin.com"), "")


class ResolveTest(TestCase):
    def test_ban_ghi_dau_tien_tao_person(self):
        result = resolution.resolve(payload())
        self.assertEqual(result.outcome, resolution.CREATED)
        self.assertEqual(result.person.display_name, "Nguyễn Văn An")
        self.assertEqual(result.person.primary_phone, "+84901234567")

    def test_cung_email_thi_khop_vao_mot_person(self):
        first = resolution.resolve(payload())
        second = resolution.resolve(payload(source="vietnamworks", cv_id="9", phone=""))
        self.assertEqual(second.outcome, resolution.MATCHED)
        self.assertEqual(second.person.pk, first.person.pk)
        self.assertEqual(Person.objects.count(), 1)

    def test_cung_dien_thoai_khac_cach_viet_van_khop(self):
        """Đây là ca chính: TopCV lưu '0901234567', VietnamWorks lưu '+84 90 123 4567'."""
        first = resolution.resolve(payload())
        second = resolution.resolve(payload(source="vietnamworks", cv_id="9",
                                            email="", phone="+84 90 123 4567"))
        self.assertEqual(second.outcome, resolution.MATCHED)
        self.assertEqual(second.person.pk, first.person.pk)

    def test_hai_nguoi_khac_nhau_khong_bi_gop(self):
        a = resolution.resolve(payload())
        b = resolution.resolve(payload(fullname="Trần Thị Bình",
                                       email="binh.tran@example.com", phone="0912345678"))
        self.assertEqual(b.outcome, resolution.CREATED)
        self.assertNotEqual(a.person.pk, b.person.pk)

    def test_trung_ten_khong_lam_gop_person(self):
        """'Nguyễn Văn An' có hàng nghìn người ở VN. Tên không phải định danh mạnh."""
        a = resolution.resolve(payload(email="an1@example.com", phone="0901111111"))
        b = resolution.resolve(payload(email="an2@example.com", phone="0902222222"))
        self.assertEqual(b.outcome, resolution.CREATED)
        self.assertNotEqual(a.person.pk, b.person.pk)

    def test_khong_co_dinh_danh_manh_thi_bo_qua(self):
        """Bản ghi chỉ có tên sẽ đẻ ra Person rác trùng tên, không ai dùng được."""
        result = resolution.resolve(payload(email="", phone="", candidate_id=""))
        self.assertEqual(result.outcome, resolution.SKIPPED)
        self.assertEqual(Person.objects.count(), 0)

    def test_dien_thoai_khong_hop_le_khong_tinh_la_dinh_danh(self):
        result = resolution.resolve(payload(email="", phone="024 3999 8888"))
        self.assertEqual(result.outcome, resolution.SKIPPED)

    def test_ma_ung_vien_cua_nguon_lam_dinh_danh(self):
        first = resolution.resolve(payload(email="", phone="", candidate_id="TCV-999"))
        self.assertEqual(first.outcome, resolution.CREATED)
        second = resolution.resolve(payload(cv_id="2", email="", phone="",
                                            candidate_id="TCV-999"))
        self.assertEqual(second.outcome, resolution.MATCHED)

    def test_cv_id_khong_duoc_dung_lam_dinh_danh_nguoi(self):
        """cv_id là mã một LƯỢT ỨNG TUYỂN, không phải mã người."""
        result = resolution.resolve(payload(email="", phone="", cv_id="12345"))
        self.assertEqual(result.outcome, resolution.SKIPPED)

    def test_dinh_danh_moi_duoc_gan_them_vao_person_da_co(self):
        first = resolution.resolve(payload(phone=""))
        resolution.resolve(payload(cv_id="2", phone="0901234567"))
        kinds = set(first.person.identities.values_list("kind", flat=True))
        self.assertEqual(kinds, {Identity.KIND_EMAIL, Identity.KIND_PHONE})

    def test_khong_ghi_de_thong_tin_da_co(self):
        """Bản ghi mới không nhất thiết đúng hơn: CV cũ tải về sau vẫn là CV cũ."""
        first = resolution.resolve(payload(position="Data Analyst"))
        resolution.resolve(payload(cv_id="2", position="Junior Intern"))
        first.person.refresh_from_db()
        self.assertEqual(first.person.headline, "")

    def test_dien_vao_cho_con_trong(self):
        first = resolution.resolve(payload(position="", city=""))
        resolution.resolve(payload(cv_id="2", position="Data Analyst", city="Hà Nội"))
        first.person.refresh_from_db()
        self.assertEqual(first.person.headline, "")
        self.assertEqual(first.person.location, "Hà Nội")


class ConflictTest(TestCase):
    """Master Plan mục 12: email → A, phone → B thì KHÔNG tự gộp."""

    def setUp(self):
        self.a = resolution.resolve(payload(email="a@example.com", phone="0901111111")).person
        self.b = resolution.resolve(payload(fullname="Người B", email="b@example.com",
                                            phone="0902222222")).person

    def test_ban_ghi_bac_cau_tao_xung_dot_chu_khong_gop(self):
        result = resolution.resolve(payload(email="a@example.com", phone="0902222222"))
        self.assertEqual(result.outcome, resolution.CONFLICT)
        self.assertIsNone(result.person)
        self.assertEqual(Person.objects.filter(merged_into__isnull=True).count(), 2,
                         "không được tự gộp")

    def test_xung_dot_duoc_ghi_kem_bang_chung(self):
        resolution.resolve(payload(email="a@example.com", phone="0902222222"))
        conflict = IdentityConflict.objects.get()
        self.assertEqual(conflict.status, IdentityConflict.STATUS_OPEN)
        self.assertEqual(set(conflict.people.values_list("pk", flat=True)),
                         {self.a.pk, self.b.pk})
        self.assertEqual(len(conflict.evidence["people"]), 2)

    def test_hai_person_bi_danh_dau_can_xem_lai(self):
        resolution.resolve(payload(email="a@example.com", phone="0902222222"))
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertTrue(self.a.needs_review)
        self.assertTrue(self.b.needs_review)

    def test_dong_bo_lai_khong_de_them_phieu_xung_dot(self):
        for _ in range(3):
            resolution.resolve(payload(email="a@example.com", phone="0902222222"))
        self.assertEqual(IdentityConflict.objects.count(), 1)

    def test_xung_dot_khong_cuop_dinh_danh_cua_ai(self):
        resolution.resolve(payload(email="a@example.com", phone="0902222222"))
        self.assertEqual(Identity.objects.get(kind=Identity.KIND_EMAIL,
                                              value="a@example.com").person_id, self.a.pk)
        self.assertEqual(Identity.objects.get(kind=Identity.KIND_PHONE,
                                              value="+84902222222").person_id, self.b.pk)


class ResolveIdentityConflictTest(TestCase):
    """`resolve_identity_conflict` — logic dùng chung giữa Django admin
    (`people/admin.py::IdentityConflictAdmin`) và API (`intel/views.py`)."""

    def setUp(self):
        self.a = resolution.resolve(payload(email="a@example.com", phone="0901111111")).person
        self.b = resolution.resolve(payload(fullname="Người B", email="b@example.com",
                                            phone="0902222222")).person
        resolution.resolve(payload(cv_id="9", email="a@example.com", phone="0902222222"))
        self.conflict = IdentityConflict.objects.get()

    def test_merge_gop_vao_nguoi_tao_som_nhat(self):
        resolution.resolve_identity_conflict(self.conflict, "merge", note="test")
        self.b.refresh_from_db()
        self.assertEqual(self.b.merged_into_id, self.a.pk)
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, IdentityConflict.STATUS_MERGED)

    def test_dismiss_xoa_co_can_xem_lai_khi_het_xung_dot_mo(self):
        resolution.resolve_identity_conflict(self.conflict, "dismiss", note="test")
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, IdentityConflict.STATUS_DISMISSED)
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertFalse(self.a.needs_review)
        self.assertFalse(self.b.needs_review)

    def test_decision_khong_hop_le_nem_loi(self):
        with self.assertRaises(ValueError):
            resolution.resolve_identity_conflict(self.conflict, "khac", note="test")

    def test_conflict_da_xu_ly_thi_khong_lam_gi_them(self):
        resolution.resolve_identity_conflict(self.conflict, "dismiss")
        result = resolution.resolve_identity_conflict(self.conflict, "merge")
        self.assertEqual(result.status, IdentityConflict.STATUS_DISMISSED)
        self.b.refresh_from_db()
        self.assertIsNone(self.b.merged_into_id, "conflict đã đóng thì không được gộp lại")


class MergeTest(TestCase):
    def setUp(self):
        self.a = resolution.resolve(payload(email="a@example.com", phone="0901111111")).person
        self.b = resolution.resolve(payload(fullname="Người B", email="b@example.com",
                                            phone="0902222222")).person

    def test_gop_chuyen_dinh_danh_sang_person_chinh(self):
        resolution.merge(self.a, self.b)
        self.assertEqual(self.a.identities.count(), 4)
        self.b.refresh_from_db()
        self.assertEqual(self.b.merged_into_id, self.a.pk)

    def test_khong_xoa_person_da_gop(self):
        """Giữ lại để mọi liên kết cũ vẫn đi tới được Person đúng."""
        resolution.merge(self.a, self.b)
        self.assertTrue(Person.objects.filter(pk=self.b.pk).exists())

    def test_canonical_di_theo_chuoi_gop(self):
        resolution.merge(self.a, self.b)
        self.b.refresh_from_db()
        self.assertEqual(self.b.canonical().pk, self.a.pk)

    def test_ban_ghi_sau_khi_gop_khop_vao_person_chinh(self):
        resolution.merge(self.a, self.b)
        result = resolution.resolve(payload(cv_id="99", email="b@example.com", phone=""))
        self.assertEqual(result.outcome, resolution.MATCHED)
        self.assertEqual(result.person.pk, self.a.pk)

    def test_gop_chuyen_ca_du_lieu_lien_quan(self):
        Signal.objects.create(person=self.b, signal_type="job_seeking",
                              observed_at=timezone.now(), evidence={"post": "x"})
        Interaction.objects.create(person=self.b, action="viewed",
                                   actor_name="recruiter")
        Document.objects.create(person=self.b, sha256="a" * 64, filename="cv.pdf")
        Opportunity.objects.create(person=self.b, domain=Signal.DOMAIN_TALENT, title="X")

        resolution.merge(self.a, self.b)

        self.assertEqual(self.a.signals.count(), 1)
        self.assertEqual(self.a.interactions.count(), 1)
        self.assertEqual(self.a.documents.count(), 1)
        self.assertEqual(self.a.opportunities.count(), 1)

    def test_gop_khong_vo_rang_buoc_quan_he_duy_nhat(self):
        Relationship.objects.create(person=self.a, domain=Signal.DOMAIN_TALENT, state="warm")
        Relationship.objects.create(person=self.b, domain=Signal.DOMAIN_TALENT, state="cool")
        resolution.merge(self.a, self.b)
        self.assertEqual(self.a.relationships.count(), 1)
        self.assertEqual(self.a.relationships.get().state, "warm",
                         "giữ quan hệ của Person chính")

    def test_gop_chuyen_quan_he_nguoi_voi_nguoi_va_khong_tu_tro(self):
        from .models import ContactMention, PersonLink
        ứng_viên = Person.objects.create(display_name="Ứng viên C")
        PersonLink.objects.create(subject=ứng_viên, related=self.b,
                                  kind=PersonLink.KIND_REFERENCE)
        # b cũng là subject của một link -> sau gộp phải thành link của a
        PersonLink.objects.create(subject=self.b, related=ứng_viên,
                                  kind=PersonLink.KIND_COLLEAGUE)
        ContactMention.objects.create(subject=self.b, email="x@y.z", email_raw="x@y.z",
                                      kind=ContactMention.KIND_REFERENCE,
                                      fingerprint="fp-merge-1")

        resolution.merge(self.a, self.b)

        self.assertEqual(self.a.links_in.get(subject=ứng_viên).kind,
                         PersonLink.KIND_REFERENCE)
        self.assertEqual(self.a.links_out.get(related=ứng_viên).kind,
                         PersonLink.KIND_COLLEAGUE)
        self.assertEqual(self.a.contact_mentions.count(), 1)
        self.assertFalse(PersonLink.objects.filter(subject=self.b).exists())
        self.assertFalse(PersonLink.objects.filter(related=self.b).exists())

    def test_gop_dong_phieu_xung_dot(self):
        resolution.resolve(payload(email="a@example.com", phone="0902222222"))
        resolution.merge(self.a, self.b, note="cùng một người")
        conflict = IdentityConflict.objects.get()
        self.assertEqual(conflict.status, IdentityConflict.STATUS_MERGED)
        self.a.refresh_from_db()
        self.assertFalse(self.a.needs_review)

    def test_gop_chinh_no_la_khong_lam_gi(self):
        self.assertEqual(resolution.merge(self.a, self.a).pk, self.a.pk)

    def test_dien_cho_trong_tu_ban_trung(self):
        self.a.headline = ""
        self.a.save()
        self.b.headline = "Data Analyst"
        self.b.save()
        resolution.merge(self.a, self.b)
        self.a.refresh_from_db()
        self.assertEqual(self.a.headline, "Data Analyst")


class InteractionActorTest(TestCase):
    """actor là khoá ngoại tới User, không phải chuỗi tự do (Phase 5B)."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.User = User
        self.user = User.objects.create_user("recruiter1", password="mat-khau-rat-dai-1")
        self.person = resolution.resolve(payload()).person

    def test_chup_lai_ten_luc_ghi(self):
        row = Interaction.objects.create(person=self.person, action="viewed",
                                         actor=self.user)
        self.assertEqual(row.actor_name, "recruiter1")

    def test_xoa_tai_khoan_van_giu_duoc_lich_su(self):
        """Nhân viên nghỉ việc, nhưng lịch sử tương tác với ứng viên phải còn."""
        row = Interaction.objects.create(person=self.person, action="shortlisted",
                                         actor=self.user)
        self.user.delete()
        row.refresh_from_db()
        self.assertIsNone(row.actor_id)
        self.assertEqual(row.actor_name, "recruiter1", "tên vẫn đọc được")
        self.assertEqual(row.action, "shortlisted")

    def test_khong_ghi_de_ten_da_chup(self):
        row = Interaction.objects.create(person=self.person, action="viewed",
                                         actor=self.user, actor_name="Tên đặt tay")
        self.assertEqual(row.actor_name, "Tên đặt tay")


class IngestTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy phòng TA", edge_id="e1")

    def _record(self, **overrides):
        data = payload(**overrides)
        return SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key=f"{data['source']}|{data['account']}|{data['cv_id']}",
            payload=data, content_hash="h" + data["cv_id"],
            source=data["source"], fullname=data["fullname"],
            email=data["email"], phone=data["phone"])

    def test_phan_giai_danh_dau_ban_ghi_va_gan_person(self):
        record = self._record()
        ingest.resolve_record(record)
        record.refresh_from_db()
        self.assertEqual(record.status, SourceRecord.STATUS_RESOLVED)
        self.assertIsNotNone(record.person)

    def test_hai_nguon_cua_cung_mot_nguoi_ve_mot_person(self):
        """Chính là tiêu chí nghiệm thu của Master Plan Phase 5."""
        self._record(source="topcv", cv_id="1")
        self._record(source="vietnamworks", cv_id="2", phone="+84 90 123 4567")
        ingest.resolve_pending()

        self.assertEqual(Person.objects.count(), 1)
        person = Person.objects.get()
        self.assertEqual(person.source_records.count(), 2)

    def test_xung_dot_giu_ban_ghi_o_trang_thai_cho(self):
        self._record(cv_id="1", email="a@example.com", phone="0901111111")
        self._record(cv_id="2", email="b@example.com", phone="0902222222")
        ingest.resolve_pending()
        conflicting = self._record(cv_id="3", email="a@example.com", phone="0902222222")

        stats = ingest.resolve_pending()
        self.assertEqual(stats[resolution.CONFLICT], 1)
        conflicting.refresh_from_db()
        self.assertEqual(conflicting.status, SourceRecord.STATUS_PENDING)
        self.assertIsNone(conflicting.person)

    def test_thieu_dinh_danh_thi_van_cho_de_lan_sau_thu_lai(self):
        record = self._record(email="", phone="")
        ingest.resolve_pending()
        record.refresh_from_db()
        self.assertEqual(record.status, SourceRecord.STATUS_PENDING)

    def test_thong_ke_theo_ket_qua(self):
        self._record(cv_id="1")
        self._record(cv_id="2", email="", phone="")
        stats = ingest.resolve_pending()
        self.assertEqual(stats["processed"], 2)
        self.assertEqual(stats[resolution.CREATED], 1)
        self.assertEqual(stats[resolution.SKIPPED], 1)

    def test_chay_lai_khong_tao_them_person(self):
        self._record(cv_id="1")
        ingest.resolve_pending()
        ingest.resolve_pending()
        self.assertEqual(Person.objects.count(), 1)

    def test_xoa_person_khong_lam_mat_ban_ghi_nguon(self):
        """Bàn nhận phải giữ nguyên trạng để phân giải lại được."""
        record = self._record()
        ingest.resolve_record(record)
        Person.objects.all().delete()
        record.refresh_from_db()
        self.assertIsNone(record.person)
        self.assertEqual(record.payload["email"], "an.nguyen@example.com")


class ResolvePendingRotationTest(TestCase):
    """Hàng đợi phân giải phải xoay vòng, không được bị đói.

    Bản cũ xếp theo `pk`, nên bản ghi không phân giải được — ứng viên không có
    email lẫn điện thoại, chuyện thường trong dữ liệu thu thập thật — mãi mãi
    đứng đầu hàng. Sau khoảng 500 bản ghi như vậy, không bản ghi mới nào còn
    được xử lý, và không ai biết vì `pending` cứ tăng đều.
    """

    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e-rotate")

    def _record(self, key, **payload):
        return SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record", entity_key=key,
            content_hash=key, payload=payload)

    def test_ban_ghi_khong_phan_giai_duoc_KHONG_chan_ban_ghi_moi(self):
        # 3 bản ghi thiếu hoàn toàn định danh -> luôn SKIPPED, ở lại pending.
        for index in range(3):
            self._record(f"ket-{index}", fullname="Không rõ")
        ingest.resolve_pending(limit=3)

        # Bản ghi mới, có email, đứng SAU về pk.
        self._record("moi", fullname="Nguyễn Văn An", email="an@example.com")
        ingest.resolve_pending(limit=3)

        moi = SourceRecord.objects.get(entity_key="moi")
        self.assertEqual(moi.status, SourceRecord.STATUS_RESOLVED,
                         "Bản ghi mới bị bỏ đói sau lưng các bản ghi không "
                         "phân giải được")

    def test_dong_dau_thoi_diem_da_thu(self):
        record = self._record("thu", fullname="Không rõ")
        received_at = record.last_seen_at
        ingest.resolve_pending()
        record.refresh_from_db()
        self.assertIsNotNone(record.resolve_attempted_at)
        self.assertEqual(record.status, SourceRecord.STATUS_PENDING)
        self.assertEqual(record.last_seen_at, received_at)

    def test_chua_thu_lan_nao_duoc_uu_tien(self):
        cu = self._record("cu", fullname="Không rõ")
        SourceRecord.objects.filter(pk=cu.pk).update(
            resolve_attempted_at=timezone.now())
        moi = self._record("chua-thu", fullname="Không rõ")

        queryset = (SourceRecord.objects
                    .filter(status=SourceRecord.STATUS_PENDING)
                    .order_by(F("resolve_attempted_at").asc(nulls_first=True), "pk"))
        self.assertEqual(queryset.first().pk, moi.pk)

    def test_ban_ghi_da_phan_giai_cung_duoc_dong_dau(self):
        record = self._record("ok", fullname="Trần Bình", email="binh@example.com")
        received_at = record.last_seen_at
        ingest.resolve_pending()
        row = SourceRecord.objects.get(entity_key="ok")
        self.assertEqual(row.status, SourceRecord.STATUS_RESOLVED)
        self.assertIsNotNone(row.resolve_attempted_at)
        self.assertEqual(row.last_seen_at, received_at)


class MergeSharedDocumentTest(TestCase):
    """Gộp hai Person cùng giữ một file CV — tình huống hay gặp nhất khi gộp.

    Một người ứng tuyển hai nơi, nộp cùng một file, được khớp bằng email ở
    nguồn này và bằng điện thoại ở nguồn kia. Bản cũ dùng
    `duplicate.documents.update(person=primary)` nên ném `IntegrityError` do
    ràng buộc `(person, sha256)` — thao tác gộp hỏng đúng lúc nó cần nhất.
    """

    def setUp(self):
        self.a = Person.objects.create(display_name="Nguyễn Văn An")
        self.b = Person.objects.create(display_name="Nguyen Van An")

    def _document(self, person, sha, storage_key=""):
        return Document.objects.create(person=person, sha256=sha,
                                       filename=f"{sha}.pdf",
                                       storage_key=storage_key)

    def test_gop_duoc_khi_hai_nguoi_chung_mot_CV(self):
        self._document(self.a, "sha-chung")
        self._document(self.b, "sha-chung")
        resolution.merge(self.a, self.b)
        self.b.refresh_from_db()
        self.assertEqual(self.b.merged_into_id, self.a.pk)
        self.assertEqual(self.a.documents.filter(sha256="sha-chung").count(), 1)

    def test_tai_lieu_rieng_van_duoc_chuyen_sang(self):
        self._document(self.a, "sha-a")
        self._document(self.b, "sha-b")
        resolution.merge(self.a, self.b)
        self.assertEqual(
            set(self.a.documents.values_list("sha256", flat=True)),
            {"sha-a", "sha-b"})

    def test_giu_lai_duong_dan_kho_khi_ban_kia_co_file_that(self):
        """Bản của primary chỉ có metadata, bản của duplicate có file thật."""
        self._document(self.a, "sha-chung", storage_key="")
        self._document(self.b, "sha-chung", storage_key="ab/cd/sha-chung")
        resolution.merge(self.a, self.b)
        keeper = self.a.documents.get(sha256="sha-chung")
        self.assertEqual(keeper.storage_key, "ab/cd/sha-chung",
                         "Mất đường dẫn kho nghĩa là mất file")

    def test_khong_mat_dau_luot_ung_tuyen_cua_ban_bi_xoa(self):
        edge = Edge.objects.create(label="Máy TA", edge_id="e-merge")
        record = SourceRecord.objects.create(
            edge=edge, entity_type="source_record", entity_key="topcv|a|9",
            content_hash="h9")
        keeper = self._document(self.a, "sha-chung")
        loser = self._document(self.b, "sha-chung")
        loser.source_records.add(record)

        resolution.merge(self.a, self.b)
        keeper.refresh_from_db()
        self.assertIn(record.pk,
                      keeper.source_records.values_list("pk", flat=True))

    def test_gop_person_cung_gop_va_khu_trung_text_parsing(self):
        from people.models import ParsedTextVersion
        from people.parsed_text import save_parsed_text

        first = self._document(self.a, "sha-a")
        second = self._document(self.b, "sha-b")
        save_parsed_text(first, "Python và SQL", origin="edge", quality_score=0.8)
        save_parsed_text(second, " Python  và SQL ", origin="hub_ai", quality_score=0.9)
        resolution.merge(self.a, self.b)
        moved = self.a.documents.get(sha256="sha-b")
        moved.refresh_from_db()
        self.assertEqual(ParsedTextVersion.objects.filter(person=self.a).count(), 1)
        self.assertEqual(moved.primary_text_version.person_id, self.a.pk)
