# -*- coding: utf-8 -*-
"""Kiểm thử phân quyền và nhật ký truy cập (Phase 5B).

Hai điều được canh:

1. **Vai trò thật sự chặn được.** Chặn ở phía máy chủ, không phải chỉ ẩn tab.
2. **Mọi lượt đọc dữ liệu cá nhân đều để lại dấu vết** — kể cả lượt của RB Sales
   đọc dữ liệu tuyển dụng, vốn được phép từ 19/08/2026 nhưng phải phân biệt được.
"""
import io
import json

from core.models import Edge, EdgeApiKey, SourceRecord
from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.urls import reverse
from people import ingest
from people.models import Person

from . import roles
from .models import AccessLog, AuthenticationEvent, UserLoginPolicy


def make_user(username, *role_names, superuser=False):
    roles.ensure_groups()
    if superuser:
        user = User.objects.create_superuser(username, f"{username}@x.vn", "mat-khau-dai-1")
    else:
        user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class RoleTest(TestCase):
    def test_superuser_luon_la_admin(self):
        user = make_user("sếp", superuser=True)
        self.assertIn(roles.ADMIN, roles.roles_of(user))

    def test_khong_dang_nhap_thi_khong_co_vai_tro(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(roles.roles_of(AnonymousUser()), set())

    def test_kiem_nhiem_nhieu_vai_tro(self):
        user = make_user("kiêm", roles.RECRUITER, roles.MANAGER)
        self.assertEqual(roles.roles_of(user), {roles.RECRUITER, roles.MANAGER})
        # Quyền là HỢP của các vai trò.
        self.assertTrue(roles.can_access(user, roles.MODULE_TALENT))
        self.assertTrue(roles.can_access(user, roles.MODULE_RB))

    def test_edge_operator_khong_vao_duoc_talent(self):
        user = make_user("vận hành", roles.EDGE_OPERATOR)
        self.assertFalse(roles.can_access(user, roles.MODULE_TALENT))
        self.assertTrue(roles.can_access(user, roles.MODULE_EDGE))

    def test_recruiter_khong_vao_duoc_cai_dat_AI(self):
        user = make_user("tuyển dụng", roles.RECRUITER)
        self.assertFalse(roles.can_access(user, roles.MODULE_AI_SETTINGS))

    def test_RB_SALES_DUOC_doc_talent(self):
        """Quyết định 19/08/2026 — xem docs/ACCESS_CONTROL.md mục 4.3."""
        user = make_user("sales", roles.RB_SALES)
        self.assertTrue(roles.can_access(user, roles.MODULE_TALENT))

    def test_RB_doc_talent_la_lien_nghiep_vu(self):
        """Được phép, nhưng phải phân biệt được với truy cập thông thường."""
        sales = make_user("sales", roles.RB_SALES)
        recruiter = make_user("tuyển dụng", roles.RECRUITER)
        self.assertTrue(roles.is_cross_domain(sales, roles.MODULE_TALENT))
        self.assertFalse(roles.is_cross_domain(recruiter, roles.MODULE_TALENT))

    def test_admin_va_manager_khong_tinh_la_lien_nghiep_vu(self):
        """Họ vốn được thiết kế để nhìn xuyên suốt."""
        for username, role in (("sếp", roles.MANAGER), ("quản trị", roles.ADMIN)):
            user = make_user(username, role)
            self.assertFalse(roles.is_cross_domain(user, roles.MODULE_TALENT))

    def test_ensure_groups_chay_lai_duoc(self):
        roles.ensure_groups()
        roles.ensure_groups()
        self.assertEqual(Group.objects.filter(name__in=roles.ALL_ROLES).count(),
                         len(roles.ALL_ROLES))


class AuthApiTest(TestCase):
    def setUp(self):
        self.user = make_user("tuyendung", roles.RECRUITER)

    def _login(self, username="tuyendung", password="mat-khau-dai-1"):
        return self.client.post(
            reverse("auth-login"),
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json")

    def test_dang_nhap_thanh_cong_tra_ve_vai_tro(self):
        response = self._login()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["roles"], [roles.RECRUITER])
        self.assertIn(roles.MODULE_TALENT, body["modules"])

    def test_sai_mat_khau_va_sai_ten_bao_CUNG_MOT_thong_diep(self):
        """Đừng cho biết tài khoản nào có thật."""
        sai_mat_khau = self._login(password="sai-be-bét").json()["detail"]
        sai_ten = self._login(username="khong-ton-tai").json()["detail"]
        self.assertEqual(sai_mat_khau, sai_ten)

    def test_tai_khoan_bi_vo_hieu_hoa(self):
        self.user.is_active = False
        self.user.save()
        # Django authenticate() từ chối user inactive -> 401 chứ không 403.
        self.assertIn(self._login().status_code, (401, 403))

    def test_thieu_thong_tin_thi_400(self):
        response = self.client.post(reverse("auth-login"),
                                    data=json.dumps({"username": "a"}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_me_tra_200_ke_ca_khi_chua_dang_nhap(self):
        """Chưa đăng nhập là một trạng thái, không phải một lỗi."""
        response = self.client.get(reverse("auth-me"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["authenticated"])

    def test_me_sau_khi_dang_nhap(self):
        self._login()
        body = self.client.get(reverse("auth-me")).json()
        self.assertTrue(body["authenticated"])
        self.assertEqual(body["username"], "tuyendung")

    def test_dang_xuat(self):
        self._login()
        self.client.post(reverse("auth-logout"))
        self.assertFalse(self.client.get(reverse("auth-me")).json()["authenticated"])

    def test_tai_khoan_email_otp_khong_dung_duoc_mat_khau_local(self):
        UserLoginPolicy.objects.create(user=self.user, login_type=UserLoginPolicy.TNTALENT)
        self.assertEqual(self._login().status_code, 401)


class ModulePermissionTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key="topcv|ta@msb.com.vn|1", content_hash="h1",
            payload={"source": "topcv", "account": "ta@msb.com.vn", "cv_id": "1",
                     "fullname": "Nguyễn Văn An", "email": "an@example.com",
                     "phone": "0901234567"})
        ingest.resolve_pending()
        self.person = Person.objects.get()

    def test_recruiter_vao_duoc_talent(self):
        self.client.force_login(make_user("tuyendung", roles.RECRUITER))
        self.assertEqual(self.client.get(reverse("talent-search")).status_code, 200)

    def test_edge_operator_BI_CHAN_khoi_talent(self):
        self.client.force_login(make_user("vanhanh", roles.EDGE_OPERATOR))
        response = self.client.get(reverse("talent-search"))
        self.assertEqual(response.status_code, 403)

    def test_nguoi_khong_co_vai_tro_nao_bi_chan(self):
        """Mặc định là đóng: cấp tài khoản chưa gán vai trò thì chưa vào được gì."""
        self.client.force_login(make_user("chua-gan"))
        self.assertEqual(self.client.get(reverse("talent-search")).status_code, 403)

    def test_chua_dang_nhap_bi_chan(self):
        self.assertIn(self.client.get(reverse("talent-search")).status_code, (401, 403))

    def test_khoa_edge_khong_mo_duoc_talent(self):
        _, raw = EdgeApiKey.issue(self.edge)
        response = self.client.get(reverse("talent-search"),
                                   HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertIn(response.status_code, (401, 403))

    def test_rb_sales_vao_duoc_talent(self):
        self.client.force_login(make_user("sales", roles.RB_SALES))
        self.assertEqual(self.client.get(reverse("talent-search")).status_code, 200)

    def test_recruiter_khong_doc_duoc_du_lieu_edge(self):
        self.client.force_login(make_user("recruiter-edge", roles.RECRUITER))
        self.assertEqual(self.client.get(reverse("hub-source-records")).status_code, 403)

    def test_edge_operator_doc_duoc_du_lieu_edge(self):
        self.client.force_login(make_user("operator-edge", roles.EDGE_OPERATOR))
        self.assertEqual(self.client.get(reverse("hub-source-records")).status_code, 200)

    def test_recruiter_khong_sua_duoc_cau_hinh_ai(self):
        self.client.force_login(make_user("recruiter-ai", roles.RECRUITER))
        self.assertEqual(self.client.get(reverse("ai-providers")).status_code, 403)

    def test_hiring_manager_khong_vao_duoc_xu_ly_ung_vien(self):
        self.client.force_login(make_user("hm-khong-san", roles.HIRING_MANAGER))
        self.assertEqual(self.client.get(reverse("hiring-hunts")).status_code, 403)

    def test_admin_doc_duoc_cau_hinh_ai(self):
        self.client.force_login(make_user("admin-ai", roles.ADMIN))
        self.assertEqual(self.client.get(reverse("ai-providers")).status_code, 200)


class RoleModuleMatrixTest(TestCase):
    """Admin phủ lên ma trận module mặc định để tự gán quyền cho vai trò khác."""

    def setUp(self):
        from .models import RoleModuleAccess
        self.RoleModuleAccess = RoleModuleAccess
        self.admin = make_user("quan-tri", roles.ADMIN)

    def test_mac_dinh_recruiter_khong_co_people_intake(self):
        recruiter = make_user("td", roles.RECRUITER)
        self.assertNotIn(roles.MODULE_INTAKE, roles.modules_of(recruiter))

    def test_admin_cap_them_module_cho_vai_tro(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("role-module-matrix"),
                                data={"role": roles.RECRUITER,
                                      "module": roles.MODULE_INTAKE,
                                      "enabled": True},
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        recruiter = make_user("td", roles.RECRUITER)
        self.assertIn(roles.MODULE_INTAKE, roles.modules_of(recruiter))

    def test_bat_lai_ve_mac_dinh_thi_xoa_hang_override(self):
        self.client.force_login(self.admin)
        url = reverse("role-module-matrix")
        self.client.post(url, data={"role": roles.RECRUITER,
                                    "module": roles.MODULE_INTAKE, "enabled": True},
                         content_type="application/json")
        self.assertEqual(self.RoleModuleAccess.objects.count(), 1)
        self.client.post(url, data={"role": roles.RECRUITER,
                                    "module": roles.MODULE_INTAKE, "enabled": False},
                         content_type="application/json")
        self.assertEqual(self.RoleModuleAccess.objects.count(), 0)

    def test_admin_thu_hoi_module_mac_dinh(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("role-module-matrix"),
                         data={"role": roles.EDGE_OPERATOR,
                               "module": roles.MODULE_INTAKE, "enabled": False},
                         content_type="application/json")
        operator = make_user("vh", roles.EDGE_OPERATOR)
        self.assertNotIn(roles.MODULE_INTAKE, roles.modules_of(operator))

    def test_khong_thu_hoi_duoc_quan_tri_khoi_admin(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("role-module-matrix"),
                                data={"role": roles.ADMIN,
                                      "module": roles.MODULE_ADMIN, "enabled": False},
                                content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn(roles.MODULE_ADMIN, roles.modules_of(self.admin))

    def test_khong_phai_admin_bi_chan(self):
        self.client.force_login(make_user("td", roles.RECRUITER))
        self.assertEqual(self.client.get(reverse("role-module-matrix")).status_code, 403)


class AccessLogTest(TestCase):
    def setUp(self):
        self.edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        SourceRecord.objects.create(
            edge=self.edge, entity_type="source_record",
            entity_key="topcv|ta@msb.com.vn|1", content_hash="h1",
            payload={"source": "topcv", "account": "ta@msb.com.vn", "cv_id": "1",
                     "fullname": "Nguyễn Văn An", "email": "an@example.com",
                     "phone": "0901234567"})
        ingest.resolve_pending()
        self.person = Person.objects.get()
        self.recruiter = make_user("tuyendung", roles.RECRUITER)

    def test_xem_ho_so_duoc_ghi_nhat_ky(self):
        self.client.force_login(self.recruiter)
        self.client.get(reverse("talent-person", args=[self.person.pk]))

        row = AccessLog.objects.get(action=AccessLog.ACTION_VIEW)
        self.assertEqual(row.user, self.recruiter)
        self.assertEqual(row.person_id, self.person.pk)
        self.assertEqual(row.person_name, "Nguyễn Văn An")
        self.assertFalse(row.cross_domain)

    def test_tim_kiem_ghi_lai_ca_DIEU_KIEN_tim(self):
        """Một lượt tìm trả 500 hồ sơ là 500 lần dữ liệu cá nhân được nhìn thấy."""
        self.client.force_login(self.recruiter)
        self.client.get(reverse("talent-search"), {"q": "Nguyễn", "skills": "SQL"})

        row = AccessLog.objects.get(action=AccessLog.ACTION_SEARCH)
        self.assertEqual(row.extra["q"], "Nguyễn")
        self.assertEqual(row.extra["skills"], "SQL")

    def test_RB_doc_talent_bi_danh_co_lien_nghiep_vu(self):
        """Truy cập liên nghiệp vụ là thứ kiểm toán soi đầu tiên."""
        self.client.force_login(make_user("sales", roles.RB_SALES))
        self.client.get(reverse("talent-person", args=[self.person.pk]))

        row = AccessLog.objects.get(action=AccessLog.ACTION_VIEW)
        self.assertTrue(row.cross_domain)
        self.assertEqual(row.roles, roles.RB_SALES)

    def test_chua_dang_nhap_thi_khong_ghi(self):
        self.client.get(reverse("talent-search"))
        self.assertEqual(AccessLog.objects.count(), 0)

    def test_khong_ghi_thao_tac_GHI(self):
        """Sửa dữ liệu đã có Interaction ghi kèm ngữ cảnh nghiệp vụ."""
        self.client.force_login(self.recruiter)
        self.client.patch(reverse("talent-profile-update", args=[self.person.pk]),
                          data=json.dumps({"summary": "x"}),
                          content_type="application/json")
        self.assertEqual(AccessLog.objects.count(), 0)

    def test_luu_ten_nguoi_dung_de_xoa_tai_khoan_khong_mat_dau_vet(self):
        self.client.force_login(self.recruiter)
        self.client.get(reverse("talent-person", args=[self.person.pk]))

        self.recruiter.delete()
        row = AccessLog.objects.get()
        self.assertIsNone(row.user_id)
        self.assertEqual(row.user_name, "tuyendung")

    def test_lay_IP_that_khi_chay_sau_proxy(self):
        self.client.force_login(self.recruiter)
        self.client.get(reverse("talent-search"),
                        HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1")
        self.assertEqual(AccessLog.objects.get().ip, "203.0.113.7")

    def test_luot_BI_CHAN_van_duoc_ghi_nhung_danh_dau_rieng(self):
        """Người cố vào chỗ không được phép là thông tin an ninh đáng giá.

        Nhưng phải phân biệt được: nhật ký mà "đã đọc dữ liệu" trông y hệt "bị
        chặn" thì gây hiểu nhầm còn tệ hơn không ghi.
        """
        self.client.force_login(make_user("vanhanh", roles.EDGE_OPERATOR))
        response = self.client.get(reverse("talent-search"))
        self.assertEqual(response.status_code, 403)

        row = AccessLog.objects.get()
        self.assertFalse(row.allowed)
        self.assertFalse(row.cross_domain, "bị chặn thì không tính là đọc liên nghiệp vụ")

    def test_man_hinh_van_hanh_khong_bi_tinh_la_talent(self):
        """hub-summary/edges/source-records nhìn theo góc hạ tầng, không phải con người."""
        self.client.force_login(make_user("vanhanh", roles.EDGE_OPERATOR))
        self.client.get(reverse("hub-summary"))

        row = AccessLog.objects.get()
        self.assertEqual(row.module, roles.MODULE_EDGE)
        self.assertTrue(row.allowed)
        self.assertFalse(row.cross_domain)

    def test_khong_ghi_duong_dan_ngoai_pham_vi(self):
        self.client.force_login(self.recruiter)
        self.client.get(reverse("liveness"))
        self.assertEqual(AccessLog.objects.count(), 0)

    def test_xuat_CSV_duoc_danh_dau_rieng_khong_tinh_la_xem(self):
        """Xuất và xem phải phân biệt được: xuất là lúc dữ liệu RỜI hệ thống."""
        self.client.force_login(self.recruiter)
        self.client.get(reverse("talent-search-export"))

        row = AccessLog.objects.get()
        self.assertEqual(row.action, AccessLog.ACTION_EXPORT)
        self.assertIn(row.action, AccessLog.EXFILTRATION_ACTIONS)

    def test_doc_danh_sach_co_hoi_RB_duoc_ghi_dung_module(self):
        """rb/ từng không được theo dõi — audit Phase 15 phát hiện và bổ sung."""
        self.client.force_login(make_user("sales", roles.RB_SALES))
        self.client.get(reverse("rb-opportunities"))

        row = AccessLog.objects.get()
        self.assertEqual(row.module, roles.MODULE_RB)
        self.assertEqual(row.action, AccessLog.ACTION_LIST)
        self.assertTrue(row.allowed)

    def test_xuat_CSV_RB_duoc_danh_dau_export(self):
        self.client.force_login(make_user("sales", roles.RB_SALES))
        self.client.get(reverse("rb-opportunities-export"))

        row = AccessLog.objects.get()
        self.assertEqual(row.module, roles.MODULE_RB)
        self.assertEqual(row.action, AccessLog.ACTION_EXPORT)

    def test_doc_bai_dang_social_duoc_ghi_dung_module(self):
        """social/ từng không được theo dõi — cùng phát hiện với rb/ ở trên."""
        self.client.force_login(self.recruiter)
        self.client.get(reverse("social-posts"))

        row = AccessLog.objects.get()
        self.assertEqual(row.module, roles.MODULE_SOCIAL)
        self.assertTrue(row.allowed)

    def test_hiring_nam_chung_module_talent_khong_phai_module_rieng(self):
        """HM/Recruiter đã được cấp quyền theo module Talent — hiring không tách riêng."""
        self.client.force_login(self.recruiter)
        self.client.get(reverse("hiring-needs"))

        row = AccessLog.objects.get()
        self.assertEqual(row.module, roles.MODULE_TALENT)

    def test_duong_dan_moi_chua_dang_ky_ten_van_nhan_dung_module(self):
        """Fallback theo tiền tố: quên đăng ký url_name mới thì vẫn không bị gán nhầm Talent."""
        from accounts.middleware import _default_module
        self.assertEqual(_default_module("/api/v1/rb/some-new-endpoint/"),
                         roles.MODULE_RB)
        self.assertEqual(_default_module("/api/v1/social/some-new-endpoint/"),
                         roles.MODULE_SOCIAL)
        self.assertEqual(_default_module("/api/v1/hiring/some-new-endpoint/"),
                         roles.MODULE_TALENT)

    def test_nhat_ky_hong_khong_chan_nguoi_dung(self):
        from unittest.mock import patch
        self.client.force_login(self.recruiter)
        with patch("accounts.middleware.AccessLogMiddleware._record",
                   side_effect=RuntimeError("CSDL sập")):
            response = self.client.get(reverse("talent-search"))
        self.assertEqual(response.status_code, 200)


class AccessLogApiTest(TestCase):
    def setUp(self):
        self.admin = make_user("quantri", superuser=True)
        AccessLog.objects.create(user_name="sales", action=AccessLog.ACTION_VIEW,
                                 module="talent", cross_domain=True)
        AccessLog.objects.create(user_name="tuyendung", action=AccessLog.ACTION_DOWNLOAD,
                                 module="talent")
        AccessLog.objects.create(user_name="tuyendung", action=AccessLog.ACTION_SEARCH,
                                 module="talent")

    def test_chi_admin_xem_duoc(self):
        self.client.force_login(make_user("tuyendung", roles.RECRUITER))
        self.assertEqual(self.client.get(reverse("access-log")).status_code, 403)

    def test_admin_xem_duoc(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("access-log")).json()
        self.assertEqual(body["count"], 3)

    def test_loc_truy_cap_lien_nghiep_vu(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("access-log"), {"cross_domain": "1"}).json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["user"], "sales")

    def test_loc_luot_dua_du_lieu_ra_ngoai(self):
        """Tải file/xuất Excel là lúc dữ liệu rời khỏi hệ thống."""
        self.client.force_login(self.admin)
        body = self.client.get(reverse("access-log"), {"exfiltration": "1"}).json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["action"], AccessLog.ACTION_DOWNLOAD)

    def test_tong_hop(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("access-log-summary")).json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["cross_domain"], 1)
        self.assertEqual(body["exfiltration"], 1)


class UserManagementTest(TestCase):
    def setUp(self):
        self.admin = make_user("quantri", roles.ADMIN)
        self.recruiter = make_user("tuyendung", roles.RECRUITER)

    def test_khong_phai_admin_bi_chan(self):
        self.client.force_login(self.recruiter)
        self.assertEqual(self.client.get(reverse("user-list")).status_code, 403)

    def test_admin_xem_danh_sach(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("user-list")).json()
        usernames = {row["username"] for row in body["results"]}
        self.assertEqual(usernames, {"quantri", "tuyendung"})

    def test_tao_tai_khoan_moi_kem_vai_tro(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "sales_moi", "password": "mot-mat-khau-dai-va-la",
                             "full_name": "Nguyễn Sales", "roles": [roles.RB_SALES]}),
            content_type="application/json")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["full_name"], "Nguyễn Sales")
        self.assertEqual(body["roles"], [roles.RB_SALES])

        new_user = User.objects.get(username="sales_moi")
        self.assertTrue(new_user.check_password("mot-mat-khau-dai-va-la"))
        self.assertEqual(UserLoginPolicy.type_of(new_user), UserLoginPolicy.LOCAL)

    def test_tao_tai_khoan_tntalent_khong_can_mat_khau_local(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "hr@tntalent.vn", "password": "",
                             "login_type": "tntalent", "roles": [roles.RECRUITER]}),
            content_type="application/json")
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="hr@tntalent.vn")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(UserLoginPolicy.type_of(user), UserLoginPolicy.TNTALENT)
        self.assertEqual(response.json()["login_type"], "tntalent")

    def test_tao_tay_chon_otp_suy_realm_theo_domain(self):
        """Form mới chỉ gửi login_type='otp'; backend suy TNTalent/MSB từ domain."""
        self.client.force_login(self.admin)
        tnt = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "a@tntalent.vn", "login_type": "otp"}),
            content_type="application/json")
        self.assertEqual(tnt.status_code, 201)
        self.assertEqual(tnt.json()["login_type"], "tntalent")
        msb = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "b@msb.com.vn", "login_type": "otp"}),
            content_type="application/json")
        self.assertEqual(msb.status_code, 201)
        self.assertEqual(msb.json()["login_type"], "msb")

    def test_tao_tay_otp_domain_chua_khai_bi_tu_choi(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "c@chua-khai.vn", "login_type": "otp"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Email OTP", response.json()["detail"])
        self.assertFalse(User.objects.filter(username="c@chua-khai.vn").exists())

    def test_tao_tay_email_domain_otp_tu_nhan_dien_du_la_chon_local(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "tu-nhan-dien@tntalent.vn", "password": "",
                             "login_type": "local", "roles": [roles.RECRUITER]}),
            content_type="application/json")
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="tu-nhan-dien@tntalent.vn")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(UserLoginPolicy.type_of(user), UserLoginPolicy.TNTALENT)

    def test_chuyen_email_otp_sang_local_bat_buoc_mat_khau_moi(self):
        UserLoginPolicy.objects.create(user=self.recruiter,
                                       login_type=UserLoginPolicy.TNTALENT)
        self.recruiter.set_unusable_password()
        self.recruiter.save(update_fields=["password"])
        self.client.force_login(self.admin)
        denied = self.client.patch(
            reverse("user-detail", args=[self.recruiter.pk]),
            data=json.dumps({"login_type": "local"}), content_type="application/json")
        self.assertEqual(denied.status_code, 400)
        allowed = self.client.patch(
            reverse("user-detail", args=[self.recruiter.pk]),
            data=json.dumps({"login_type": "local", "password": "mat-khau-moi-du-dai"}),
            content_type="application/json")
        self.assertEqual(allowed.status_code, 200)
        self.recruiter.refresh_from_db()
        self.assertTrue(self.recruiter.check_password("mat-khau-moi-du-dai"))

    def test_sua_tai_khoan_chon_otp_suy_realm_tu_email(self):
        """PATCH login_type='otp' suy realm từ email; email ngoài domain -> 400."""
        self.client.force_login(self.admin)
        self.recruiter.email = "tuyendung@msb.com.vn"
        self.recruiter.save(update_fields=["email"])
        ok = self.client.patch(
            reverse("user-detail", args=[self.recruiter.pk]),
            data=json.dumps({"login_type": "otp"}), content_type="application/json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(UserLoginPolicy.type_of(self.recruiter), UserLoginPolicy.MSB)

        other = make_user("ngoai_domain", roles.RECRUITER)
        other.email = "x@ngoai.vn"
        other.save(update_fields=["email"])
        bad = self.client.patch(
            reverse("user-detail", args=[other.pk]),
            data=json.dumps({"login_type": "otp"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)

    def test_trung_ten_dang_nhap_bi_tu_choi(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "tuyendung", "password": "mot-mat-khau-dai-va-la"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_trung_ten_dang_nhap_khong_phan_biet_hoa_thuong(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "TuyenDung", "password": "mot-mat-khau-dai-va-la"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="TuyenDung").exists())

    def test_trung_email_voi_tai_khoan_da_co_bi_tu_choi(self):
        """Tài khoản cũ (createsuperuser) có username rời nhưng email công ty;
        tạo tài khoản OTP mới lấy chính email đó làm username phải bị chặn —
        nếu không, đăng nhập bằng email sẽ chọn nhầm một trong hai."""
        User.objects.create_user("superadmin", email="tunglh2@tntalent.vn",
                                 password="mot-mat-khau-dai-va-la")
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "tunglh2@tntalent.vn", "login_type": "tntalent"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.filter(email__iexact="tunglh2@tntalent.vn").count(), 1)

    def test_mat_khau_yeu_bi_tu_choi(self):
        """Đây là mặt tạo tài khoản người dùng thật — dùng validator của Django,
        không phải nới lỏng như dữ liệu test nội bộ."""
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "yeu", "password": "1234"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="yeu").exists())

    def test_vai_tro_khong_ton_tai_bi_tu_choi(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("user-list"),
            data=json.dumps({"username": "x", "password": "mot-mat-khau-dai-va-la",
                             "roles": ["vai-tro-khong-co-that"]}),
            content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_sua_vai_tro(self):
        self.client.force_login(self.admin)
        response = self.client.patch(
            reverse("user-detail", args=[self.recruiter.pk]),
            data=json.dumps({"roles": [roles.RECRUITER, roles.MANAGER]}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(response.json()["roles"]),
                         sorted([roles.RECRUITER, roles.MANAGER]))

    def test_khoa_tai_khoan_nguoi_khac(self):
        target_client = Client()
        target_client.force_login(self.recruiter)
        target_session_key = target_client.session.session_key
        self.client.force_login(self.admin)
        response = self.client.patch(
            reverse("user-detail", args=[self.recruiter.pk]),
            data=json.dumps({"is_active": False}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.recruiter.refresh_from_db()
        self.assertFalse(self.recruiter.is_active)
        from django.contrib.sessions.models import Session
        self.assertFalse(Session.objects.filter(session_key=target_session_key).exists())
        event = AuthenticationEvent.objects.filter(
            user=self.recruiter, result="account_auth_policy_changed").latest("id")
        self.assertEqual(event.actor, self.admin)

    def test_khong_tu_khoa_duoc_chinh_minh(self):
        self.client.force_login(self.admin)
        response = self.client.patch(
            reverse("user-detail", args=[self.admin.pk]),
            data=json.dumps({"is_active": False}),
            content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_dat_lai_mat_khau(self):
        self.client.force_login(self.admin)
        response = self.client.patch(
            reverse("user-detail", args=[self.recruiter.pk]),
            data=json.dumps({"password": "mat-khau-moi-du-dai"}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.recruiter.refresh_from_db()
        self.assertTrue(self.recruiter.check_password("mat-khau-moi-du-dai"))


class UserBulkCreateTest(TestCase):
    """Tạo hàng loạt qua file .xlsx — xem accounts/views.py::user_bulk_create."""

    def setUp(self):
        self.admin = make_user("quantri", roles.ADMIN)
        self.recruiter = make_user("tuyendung", roles.RECRUITER)

    @staticmethod
    def _xlsx(rows, filename="tai_len.xlsx"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        for row in rows:
            sheet.append(row)
        buf = io.BytesIO()
        workbook.save(buf)
        return SimpleUploadedFile(
            filename, buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_khong_phai_admin_bi_chan(self):
        self.client.force_login(self.recruiter)
        self.assertEqual(self.client.get(reverse("user-bulk-template")).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("user-bulk-create"),
                             {"file": self._xlsx([["header"]])}).status_code,
            403)

    def test_tai_file_mau_dung_dinh_dang(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("user-bulk-template"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(response.content))
        sheet = workbook.active
        self.assertEqual([c.value for c in sheet[1][:4]],
                         ["username", "ho_ten", "vai_tro", "loai_dang_nhap"])
        # Vùng A2:D2 (dòng dữ liệu đầu tiên) phải trống — không còn dòng ví dụ
        # giả nào trong vùng mà user_bulk_create thật sự đọc.
        self.assertEqual([sheet.cell(row=2, column=c).value for c in (1, 2, 3, 4)],
                         [None, None, None, None])
        # Bảng tra vai trò ở cột E/F, tách khỏi vùng nhập liệu.
        role_keys_in_sheet = {sheet.cell(row=r, column=7).value for r in range(2, 8)}
        self.assertTrue(set(roles.ALL_ROLES).issubset(role_keys_in_sheet))

    def test_tao_hang_loat_thanh_cong(self):
        self.client.force_login(self.admin)
        xlsx_file = self._xlsx([
            ["username", "ho_ten", "vai_tro", "loai_dang_nhap"],
            ["nguyenvana", "Nguyen Van A", f"{roles.RECRUITER}|{roles.MANAGER}", "local"],
            ["tranthib", "Tran Thi B", "", "local"],
        ])
        response = self.client.post(reverse("user-bulk-create"), {"file": xlsx_file})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["created"], 2)
        self.assertEqual(body["total"], 2)

        an = User.objects.get(username="nguyenvana")
        self.assertEqual(sorted(roles.roles_of(an)), sorted([roles.RECRUITER, roles.MANAGER]))
        # Mật khẩu trả về đúng một lần trong kết quả phải dùng đăng nhập được.
        row = next(r for r in body["results"] if r["username"] == "nguyenvana")
        self.assertTrue(an.check_password(row["password"]))

    def test_tao_hang_loat_phan_biet_ba_loai_dang_nhap(self):
        self.client.force_login(self.admin)
        xlsx_file = self._xlsx([
            ["username", "ho_ten", "vai_tro", "loai_dang_nhap"],
            ["local1", "Local", roles.ADMIN, "local"],
            ["hr@tntalent.vn", "HR", roles.RECRUITER, "local"],
            ["rm@msb.com.vn", "RM", roles.RB_SALES, "msb"],
        ])
        body = self.client.post(reverse("user-bulk-create"), {"file": xlsx_file}).json()
        self.assertEqual(body["created"], 3)
        self.assertTrue(User.objects.get(username="local1").has_usable_password())
        for username, expected in (("hr@tntalent.vn", "tntalent"),
                                   ("rm@msb.com.vn", "msb")):
            user = User.objects.get(username=username)
            self.assertFalse(user.has_usable_password())
            self.assertEqual(UserLoginPolicy.type_of(user), expected)
            result = next(row for row in body["results"] if row["username"] == username)
            self.assertEqual(result["password"], "")

    def test_hang_loat_otp_domain_chua_khai_bi_tu_choi_khong_tao_am_tham(self):
        self.client.force_login(self.admin)
        xlsx_file = self._xlsx([
            ["username", "ho_ten", "vai_tro", "loai_dang_nhap"],
            ["ok@tntalent.vn", "OK", "", "otp"],
            ["x@chua-khai.vn", "Chua khai domain", "", "otp"],
        ])
        body = self.client.post(reverse("user-bulk-create"), {"file": xlsx_file}).json()
        self.assertEqual(body["created"], 1)
        statuses = {r["username"]: r["status"] for r in body["results"]}
        self.assertEqual(statuses["ok@tntalent.vn"], "created")
        self.assertEqual(statuses["x@chua-khai.vn"], "rejected")
        self.assertFalse(User.objects.filter(username="x@chua-khai.vn").exists())

    def test_dong_loi_khong_lam_hong_dong_khac(self):
        self.client.force_login(self.admin)
        xlsx_file = self._xlsx([
            ["username", "ho_ten", "vai_tro", "loai_dang_nhap"],
            ["tuyendung", "Trung ten co san", "", "local"],
            ["", "Thieu ten", "", "local"],
            ["ai_do", "Vai tro sai", "khong-co-that", "local"],
            ["nguoi_moi", "Nguoi Moi", "", "local"],
        ])
        response = self.client.post(reverse("user-bulk-create"), {"file": xlsx_file})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["total"], 4)
        statuses = {r["username"]: r["status"] for r in body["results"]}
        self.assertEqual(statuses["tuyendung"], "rejected")
        self.assertEqual(statuses["ai_do"], "rejected")
        self.assertEqual(statuses["nguoi_moi"], "created")
        self.assertTrue(User.objects.filter(username="nguoi_moi").exists())

    def test_trung_ten_trong_cung_file(self):
        self.client.force_login(self.admin)
        xlsx_file = self._xlsx([
            ["username", "ho_ten", "vai_tro", "loai_dang_nhap"],
            ["trung_ten", "Lan 1", "", "local"],
            ["trung_ten", "Lan 2", "", "local"],
            ["Trung_Ten", "Lan 3 hoa thuong khac", "", "local"],
        ])
        response = self.client.post(reverse("user-bulk-create"), {"file": xlsx_file})
        body = response.json()
        self.assertEqual(body["created"], 1)
        self.assertEqual(User.objects.filter(username__iexact="trung_ten").count(), 1)

    def test_trung_email_voi_tai_khoan_da_co_bi_tu_choi(self):
        User.objects.create_user("superadmin", email="hr@tntalent.vn",
                                 password="mot-mat-khau-dai-va-la")
        self.client.force_login(self.admin)
        xlsx_file = self._xlsx([
            ["username", "ho_ten", "vai_tro", "loai_dang_nhap"],
            ["hr@tntalent.vn", "Trung email tai khoan cu", "", "tntalent"],
        ])
        body = self.client.post(reverse("user-bulk-create"), {"file": xlsx_file}).json()
        self.assertEqual(body["created"], 0)
        self.assertEqual(body["results"][0]["status"], "rejected")
        self.assertEqual(User.objects.filter(email__iexact="hr@tntalent.vn").count(), 1)

    def test_khong_co_file_bi_tu_choi(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("user-bulk-create"), {})
        self.assertEqual(response.status_code, 400)

    def test_file_khong_phai_xlsx_bi_tu_choi(self):
        self.client.force_login(self.admin)
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake = SimpleUploadedFile("tai_len.xlsx", b"khong phai file xlsx that",
                                  content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response = self.client.post(reverse("user-bulk-create"), {"file": fake})
        self.assertEqual(response.status_code, 400)
