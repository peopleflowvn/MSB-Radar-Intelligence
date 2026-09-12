# -*- coding: utf-8 -*-
"""Che liên hệ, hạn mức mở khoá và ranh giới file CV (Master Plan mục 27).

Điều bài này canh kỹ nhất: **không có đường vòng**. Danh sách che vô điều kiện,
xuất CSV cũng che, và cửa duy nhất lấy được liên hệ đầy đủ là endpoint mở khoá —
nơi có đếm hạn mức và có ghi vết.

Một lớp bảo vệ chỉ cần hở đúng một endpoint là mất tác dụng hoàn toàn, nên
`ChoDuongVongTest` đi qua từng đường ra dữ liệu chứ không chỉ kiểm cái chính.
"""
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from people.models import Person

from . import privacy, roles
from .models import ContactUnlockLog, ContactUnlockPolicy


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class MaskTest(TestCase):
    """Hàm che phải che thật — trả về nguyên văn là một lỗ rò im lặng."""

    def test_che_email_giu_ten_mien(self):
        got = privacy.mask_email("nguyen.van.an@gmail.com")
        self.assertTrue(got.endswith("@gmail.com"))
        self.assertNotIn("van.an", got)
        self.assertIn("***", got)

    def test_che_so_dien_thoai_giu_dau_cuoi(self):
        got = privacy.mask_phone("0975219309")
        self.assertTrue(got.startswith("097"))
        self.assertTrue(got.endswith("309"))
        self.assertNotEqual(got, "0975219309")

    def test_chuoi_rong_van_la_chuoi_rong(self):
        self.assertEqual(privacy.mask_email(""), "")
        self.assertEqual(privacy.mask_phone(""), "")
        self.assertEqual(privacy.mask_email(None), "")

    def test_gia_tri_NGAN_van_bi_che(self):
        """Không được trả nguyên văn chỉ vì dữ liệu ngắn."""
        for value in ("a@b.vn", "ab@c.vn", "x"):
            self.assertNotEqual(privacy.mask_email(value), value, value)
        for value in ("0975", "097", "1"):
            self.assertNotEqual(privacy.mask_phone(value), value, value)

    def test_khong_dung_khuon_email_van_bi_che(self):
        self.assertNotEqual(privacy.mask_email("khongcoat"), "khongcoat")


class QuotaTest(TestCase):
    def setUp(self):
        self.recruiter = make_user("tuyendung-quota", roles.RECRUITER)
        self.rm = make_user("rm-quota", roles.RB_SALES)
        self.an = Person.objects.create(display_name="Nguyễn Văn An",
                                        primary_phone="+84901234567",
                                        primary_email="an@example.com")

    def test_han_muc_mac_dinh_theo_vai_tro(self):
        self.assertEqual(privacy.quota_for(self.recruiter),
                         privacy.DEFAULT_DAILY_QUOTA[roles.RECRUITER])
        self.assertEqual(privacy.quota_for(self.rm),
                         privacy.DEFAULT_DAILY_QUOTA[roles.RB_SALES])

    def test_RM_thap_hon_recruiter(self):
        """RM làm theo từng khách; recruiter sàng theo lô."""
        self.assertLess(privacy.quota_for(self.rm), privacy.quota_for(self.recruiter))

    def test_kiem_nhieu_vai_tro_thi_lay_muc_CAO_NHAT_khong_cong_don(self):
        kiem = make_user("kiem-nhiem", roles.RECRUITER, roles.RB_SALES)
        self.assertEqual(privacy.quota_for(kiem),
                         max(privacy.DEFAULT_DAILY_QUOTA[roles.RECRUITER],
                             privacy.DEFAULT_DAILY_QUOTA[roles.RB_SALES]))

    def test_quan_ly_VAN_co_han_muc(self):
        """Chốt kiểm soát chỉ áp cho cấp dưới thì không phải chốt kiểm soát."""
        manager = make_user("quan-ly", roles.MANAGER)
        self.assertIsNotNone(privacy.quota_for(manager))

    def test_admin_khong_gioi_han(self):
        admin = make_user("quan-tri", roles.ADMIN)
        self.assertIsNone(privacy.quota_for(admin))

    def test_cap_han_muc_rieng(self):
        ContactUnlockPolicy.objects.create(user=self.rm, custom_daily_quota=99,
                                           reason="Chiến dịch trọng điểm")
        self.assertEqual(privacy.quota_for(self.rm), 99)

    def test_co_khong_gioi_han_thang_moi_muc_khac(self):
        ContactUnlockPolicy.objects.create(user=self.rm, is_unlimited=True,
                                           custom_daily_quota=5)
        self.assertIsNone(privacy.quota_for(self.rm))

    def test_vai_tro_la_thi_han_muc_thap(self):
        khach = make_user("khong-vai-tro")
        self.assertEqual(privacy.quota_for(khach), privacy.FALLBACK_QUOTA)

    def test_mo_khoa_tru_dung_mot_luot(self):
        truoc = privacy.remaining(self.rm)
        privacy.unlock(self.rm, self.an, domain="rb")
        self.assertEqual(privacy.remaining(self.rm), truoc - 1)

    def test_mo_LAI_cung_nguoi_trong_ngay_KHONG_tru_them(self):
        """Trừ lượt khi mở lại sẽ dạy người dùng chụp màn hình cả danh sách."""
        privacy.unlock(self.rm, self.an, domain="rb")
        con_lai = privacy.remaining(self.rm)
        _contact, sau, charged = privacy.unlock(self.rm, self.an, domain="rb")
        self.assertEqual(sau, con_lai)
        self.assertFalse(charged)
        self.assertEqual(ContactUnlockLog.objects.count(), 1)

    def test_het_han_muc_thi_bi_chan(self):
        ContactUnlockPolicy.objects.create(user=self.rm, custom_daily_quota=1)
        privacy.unlock(self.rm, self.an, domain="rb")
        khac = Person.objects.create(display_name="Người khác",
                                     primary_phone="+84909999999")
        with self.assertRaises(privacy.QuotaExceeded):
            privacy.unlock(self.rm, khac, domain="rb")

    def test_han_muc_reset_theo_ngay(self):
        ContactUnlockPolicy.objects.create(user=self.rm, custom_daily_quota=1)
        privacy.unlock(self.rm, self.an, domain="rb")
        # Đẩy lượt hôm nay về hôm qua.
        ContactUnlockLog.objects.update(
            unlocked_at=timezone.now() - timedelta(days=1))
        self.assertEqual(privacy.remaining(self.rm), 1)

    def test_moi_luot_mo_khoa_deu_duoc_ghi_vet(self):
        privacy.unlock(self.rm, self.an, domain="rb", ip="10.0.0.5")
        row = ContactUnlockLog.objects.get()
        self.assertEqual(row.user, self.rm)
        self.assertEqual(row.person, self.an)
        self.assertEqual(row.domain, "rb")
        self.assertEqual(row.ip, "10.0.0.5")
        # Tên chụp lại lúc mở khoá: xoá tài khoản không được làm mất dấu vết.
        self.assertEqual(row.user_name, str(self.rm))
        self.assertEqual(row.person_name, "Nguyễn Văn An")

    def test_xoa_tai_khoan_khong_xoa_dau_vet(self):
        privacy.unlock(self.rm, self.an, domain="rb")
        self.rm.delete()
        row = ContactUnlockLog.objects.get()
        self.assertIsNone(row.user)
        self.assertTrue(row.user_name)


class UnlockApiTest(TestCase):
    def setUp(self):
        self.rm = make_user("rm-api-unlock", roles.RB_SALES)
        self.client.force_login(self.rm)
        self.an = Person.objects.create(display_name="Nguyễn Văn An",
                                        primary_phone="+84901234567",
                                        primary_email="an@example.com")

    def test_mo_khoa_tra_ve_lien_he_day_du(self):
        response = self.client.post(
            reverse("contact-unlock", args=[self.an.pk]),
            {"domain": "rb"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["primary_phone"], "+84901234567")
        self.assertEqual(body["primary_email"], "an@example.com")
        self.assertTrue(body["charged"])

    def test_het_han_muc_tra_429_khong_phai_403(self):
        """403 khiến người dùng tưởng mất quyền và đi hỏi quản trị viên."""
        ContactUnlockPolicy.objects.create(user=self.rm, custom_daily_quota=0)
        response = self.client.post(
            reverse("contact-unlock", args=[self.an.pk]),
            {"domain": "rb"}, content_type="application/json")
        self.assertEqual(response.status_code, 429)
        self.assertIn("hạn mức", response.json()["detail"])

    def test_ho_so_khong_ton_tai_tra_404(self):
        response = self.client.post(reverse("contact-unlock", args=[999999]),
                                    {}, content_type="application/json")
        self.assertEqual(response.status_code, 404)

    def test_nghiep_vu_la_bi_tu_choi(self):
        response = self.client.post(
            reverse("contact-unlock", args=[self.an.pk]),
            {"domain": "khong-co"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_vai_tro_khong_nghiep_vu_bi_chan(self):
        """Tài khoản vận hành Edge không có lý do gì để lấy số ứng viên."""
        edge = make_user("edge-op", roles.EDGE_OPERATOR)
        self.client.force_login(edge)
        response = self.client.post(
            reverse("contact-unlock", args=[self.an.pk]),
            {}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_chua_dang_nhap_bi_chan(self):
        self.client.logout()
        response = self.client.post(reverse("contact-unlock", args=[self.an.pk]),
                                    {}, content_type="application/json")
        self.assertIn(response.status_code, (401, 403))

    def test_xem_duoc_han_muc_con_lai(self):
        body = self.client.get(reverse("contact-unlock-quota")).json()
        self.assertEqual(body["limit"], privacy.DEFAULT_DAILY_QUOTA[roles.RB_SALES])
        self.assertEqual(body["used"], 0)


class ChoDuongVongTest(TestCase):
    """Đi qua TỪNG đường ra dữ liệu: hở một chỗ là cả lớp bảo vệ vô nghĩa."""

    def setUp(self):
        self.recruiter = make_user("tuyendung-vong", roles.RECRUITER)
        self.an = Person.objects.create(display_name="Nguyễn Văn An",
                                        primary_phone="+84901234567",
                                        primary_email="an@example.com")

    def test_tim_kiem_talent_da_che(self):
        self.client.force_login(self.recruiter)
        body = self.client.get(reverse("talent-search")).json()
        row = next(r for r in body["results"] if r["id"] == self.an.pk)
        self.assertNotEqual(row["primary_phone"], "+84901234567")
        self.assertTrue(row["contact_masked"])

    def test_person_360_da_che(self):
        self.client.force_login(self.recruiter)
        body = self.client.get(reverse("talent-person", args=[self.an.pk])).json()
        self.assertNotEqual(body["primary_phone"], "+84901234567")
        self.assertNotEqual(body["primary_email"], "an@example.com")

    def test_xuat_CSV_talent_da_che(self):
        """Xuất file là lúc dữ liệu RỜI KHỎI hệ thống — đường rò nguy hiểm nhất."""
        self.client.force_login(self.recruiter)
        text = self.client.get(reverse("talent-search-export")).content.decode("utf-8-sig")
        self.assertIn("Nguyễn Văn An", text)
        self.assertNotIn("+84901234567", text)
        self.assertNotIn("an@example.com", text)

    def test_xuat_CSV_rb_da_che(self):
        from rb.models import PRODUCT_MORTGAGE, RBOpportunity

        rm = make_user("rm-csv", roles.RB_SALES)
        RBOpportunity.objects.create(person=self.an, product=PRODUCT_MORTGAGE)
        self.client.force_login(rm)
        text = self.client.get(
            reverse("rb-opportunities-export")).content.decode("utf-8-sig")
        self.assertIn("Nguyễn Văn An", text)
        self.assertNotIn("+84901234567", text)

    def test_ban_ghi_nguon_da_che(self):
        """Lỗ hổng cuối: vai trò VẬN HÀNH đọc được liên hệ toàn kho bằng lật trang.

        `/hub/source-records/` trả 200 dòng mỗi lần và có tìm kiếm theo email —
        đúng kịch bản đọc hàng loạt mà cả cơ chế che sinh ra để chặn, và nó đi
        vòng qua toàn bộ `accounts/privacy.py`.
        """
        from core.models import Edge, SourceRecord

        edge = Edge.objects.create(label="Máy TA", edge_id="e-privacy")
        SourceRecord.objects.create(
            edge=edge, entity_type="source_record", entity_key="topcv|a|1",
            content_hash="h-privacy", source="topcv", fullname="Nguyễn Văn An",
            email="an@example.com", phone="+84901234567")

        self.client.force_login(make_user("edge-op-privacy", roles.EDGE_OPERATOR))
        payload = self.client.get(reverse("hub-source-records")).content.decode("utf-8")
        self.assertIn("Nguy", payload)                 # vẫn thấy tên để đối chiếu
        self.assertNotIn("an@example.com", payload)
        self.assertNotIn("+84901234567", payload)

    def test_co_hoi_hom_nay_khong_lo_lien_he(self):
        """Màn hình mới nhất cũng phải theo đúng luật, không được miễn trừ."""
        from rb.models import PRODUCT_MORTGAGE, RBOpportunity

        rm = make_user("rm-today-privacy", roles.RB_SALES)
        RBOpportunity.objects.create(person=self.an, product=PRODUCT_MORTGAGE)
        self.client.force_login(rm)
        payload = self.client.get(reverse("rb-today")).content.decode("utf-8")
        self.assertNotIn("+84901234567", payload)
        self.assertNotIn("an@example.com", payload)


class CvFileBoundaryTest(TestCase):
    """RM tuyệt đối không xem/tải file CV gốc (Master Plan mục 27.4)."""

    def setUp(self):
        from people.models import Document

        self.an = Person.objects.create(display_name="Nguyễn Văn An")
        self.document = Document.objects.create(
            person=self.an, filename="cv-an.pdf", storage_key="",
            mime_type="application/pdf")

    def test_RM_khong_tai_duoc_file_CV(self):
        rm = make_user("rm-cv", roles.RB_SALES)
        self.client.force_login(rm)
        response = self.client.get(
            reverse("talent-document-download", args=[self.document.pk]))
        self.assertEqual(response.status_code, 403)

    def test_recruiter_van_tai_duoc(self):
        """Chặn RM không được làm hỏng việc của recruiter."""
        recruiter = make_user("tuyendung-cv", roles.RECRUITER)
        self.client.force_login(recruiter)
        response = self.client.get(
            reverse("talent-document-download", args=[self.document.pk]))
        # 404 vì bản ghi demo chưa có file thật — điều cần canh là KHÔNG phải 403.
        self.assertNotEqual(response.status_code, 403)


class RedactInTextTest(TestCase):
    """Che theo trường không đủ — liên hệ còn nằm trong văn bản tự do.

    Bằng chứng của một đề xuất chứa trích dẫn nguyên văn bài đăng, và người ta
    thường tự viết số điện thoại vào bài. Trích dẫn đó hiện thẳng trên thẻ
    «Cơ hội hôm nay», nên không che ở đây thì toàn bộ hạn mức mở khoá bị đi
    vòng qua bằng một đường không ai nghĩ tới mà đi kiểm.
    """

    def test_che_so_dien_thoai_trong_cau(self):
        got = privacy.redact_contacts("Em cần vay mua nhà, LH 0901234567 nhé")
        self.assertNotIn("0901234567", got)
        self.assertIn("mua nhà", got)

    def test_che_so_co_ma_vung_va_dau_cach(self):
        for raw in ("+84901234567", "+84 901 234 567", "090-123-4567"):
            self.assertNotIn(raw, privacy.redact_contacts(f"gọi {raw} giúp em"))

    def test_che_email_trong_cau(self):
        got = privacy.redact_contacts("liên hệ an.nguyen@example.com giúp em")
        self.assertNotIn("an.nguyen@example.com", got)
        self.assertIn("example.com", got, "giữ tên miền để còn đối chiếu được")

    def test_van_ban_khong_co_lien_he_giu_nguyen(self):
        text = "Em đang tìm hiểu gói vay mua nhà 500 triệu"
        self.assertEqual(privacy.redact_contacts(text), text)

    def test_chuoi_rong_khong_no(self):
        self.assertEqual(privacy.redact_contacts(""), "")
        self.assertEqual(privacy.redact_contacts(None), "")

    def test_bang_chung_de_xuat_khong_lo_so_dien_thoai(self):
        """Đường đi thật: bài đăng → tín hiệu → đề xuất → thẻ."""
        from people.models import Signal
        from rb import suggestions

        person = Person.objects.create(display_name="Nguyễn Văn An",
                                       primary_phone="+84901234567")
        signal = Signal.objects.create(
            person=person, domain="rb", signal_type="financial_need",
            source="facebook", confidence=0.9,
            evidence={"excerpt": "Em cần vay mua nhà, LH 0901234567"},
            observed_at=timezone.now())
        made = suggestions.from_signal(signal)
        self.assertTrue(made)
        why = " ".join(made[0].evidence["why"])
        self.assertNotIn("0901234567", why)
