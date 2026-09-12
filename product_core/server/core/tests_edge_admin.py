# -*- coding: utf-8 -*-
"""Tự phục vụ tạo Edge + cấp/thu hồi khoá — nền tảng cho triển khai đa doanh nghiệp.

Ba điều bài này canh kỹ nhất:

1. **Khoá thô chỉ xuất hiện đúng một lần**, ở đúng phản hồi cấp khoá. Mọi
   endpoint khác — kể cả xem lại chính Edge đó — không bao giờ trả `api_key`.
2. **Tạo Edge và cấp khoá đòi quyền Admin**, xem đòi `RequiresEdgeOps` — đây là
   hành động sinh ra thông tin xác thực, không phải hành động vận hành thường.
3. **Endpoint cũ `hub/edges/` không đổi khuôn** — nhiều nơi khác đang phụ thuộc
   đúng hình dạng cũ của nó.
"""
from accounts import roles
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import Edge, EdgeApiKey, SourceRecord


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class EdgeCollectionTest(TestCase):
    def setUp(self):
        self.admin = make_user("quan-tri-edge", roles.ADMIN)
        self.edge_op = make_user("van-hanh-edge", roles.EDGE_OPERATOR)

    def test_admin_tao_duoc_Edge_moi(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("edge-admin-edges"),
            {"label": "Máy phòng Tuyển dụng — tầng 12"},
            content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Edge.objects.count(), 1)
        self.assertEqual(response.json()["api_keys"], [])

    def test_ten_gop_rong_bi_tu_choi(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("edge-admin-edges"), {"label": "  "},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_van_hanh_edge_XEM_duoc_nhung_KHONG_tao_duoc(self):
        """Xem danh sách là vận hành thường; tạo Edge là sinh thông tin xác thực."""
        self.client.force_login(self.edge_op)
        self.assertEqual(self.client.get(reverse("edge-admin-edges")).status_code, 200)
        response = self.client.post(reverse("edge-admin-edges"), {"label": "X"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Edge.objects.count(), 0)

    def test_vai_tro_khac_khong_xem_duoc(self):
        self.client.force_login(make_user("tuyendung-edge", roles.RECRUITER))
        self.assertEqual(self.client.get(reverse("edge-admin-edges")).status_code, 403)

    def test_chua_dang_nhap_bi_chan(self):
        response = self.client.get(reverse("edge-admin-edges"))
        self.assertIn(response.status_code, (401, 403))

    def test_danh_sach_kem_khoa_nhung_KHONG_co_khoa_tho(self):
        edge = Edge.objects.create(label="Máy A")
        EdgeApiKey.issue(edge, name="Đợt 1")
        self.client.force_login(self.edge_op)
        body = self.client.get(reverse("edge-admin-edges")).json()
        row = body["results"][0]
        self.assertEqual(len(row["api_keys"]), 1)
        self.assertNotIn("api_key", row["api_keys"][0])
        self.assertNotIn("key_hash", row["api_keys"][0])


class EdgeDetailTest(TestCase):
    def setUp(self):
        self.admin = make_user("quan-tri-sua", roles.ADMIN)
        self.edge = Edge.objects.create(label="Máy cũ")
        self.client.force_login(self.admin)

    def test_doi_ten(self):
        response = self.client.patch(
            reverse("edge-admin-edge-detail", args=[self.edge.pk]),
            {"label": "Máy mới"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.edge.refresh_from_db()
        self.assertEqual(self.edge.label, "Máy mới")

    def test_tat_khong_thu_hoi_khoa(self):
        """Tắt Edge không thu hồi khoá — hai hành động khác nhau, xem docstring."""
        _record, _raw = EdgeApiKey.issue(self.edge)
        response = self.client.patch(
            reverse("edge-admin-edge-detail", args=[self.edge.pk]),
            {"is_active": False}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(EdgeApiKey.objects.get(edge=self.edge).is_active)

    def test_khong_co_gi_de_cap_nhat(self):
        response = self.client.patch(
            reverse("edge-admin-edge-detail", args=[self.edge.pk]),
            {}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_van_hanh_edge_khong_sua_duoc(self):
        self.client.force_login(make_user("van-hanh-sua", roles.EDGE_OPERATOR))
        response = self.client.patch(
            reverse("edge-admin-edge-detail", args=[self.edge.pk]),
            {"label": "X"}, content_type="application/json")
        self.assertEqual(response.status_code, 403)


class EdgeDeleteTest(TestCase):
    def setUp(self):
        self.admin = make_user("quan-tri-xoa", roles.ADMIN)
        self.edge = Edge.objects.create(label="Máy tạm")
        self.client.force_login(self.admin)

    def test_xoa_Edge_chua_co_du_lieu(self):
        response = self.client.delete(
            reverse("edge-admin-edge-detail", args=[self.edge.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted"], True)
        self.assertFalse(Edge.objects.filter(pk=self.edge.pk).exists())

    def test_khong_xoa_duoc_Edge_da_co_du_lieu(self):
        """Dữ liệu thô là bất biến — xoá Edge không được phép kéo theo mất bản ghi nguồn."""
        SourceRecord.objects.create(
            edge=self.edge, entity_type="candidate", entity_key="cv-1", content_hash="h1",
        )
        response = self.client.delete(
            reverse("edge-admin-edge-detail", args=[self.edge.pk]))
        self.assertEqual(response.status_code, 409)
        self.assertTrue(Edge.objects.filter(pk=self.edge.pk).exists())
        self.assertEqual(SourceRecord.objects.filter(edge=self.edge).count(), 1)

    def test_van_hanh_edge_khong_xoa_duoc(self):
        self.client.force_login(make_user("van-hanh-xoa", roles.EDGE_OPERATOR))
        response = self.client.delete(
            reverse("edge-admin-edge-detail", args=[self.edge.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Edge.objects.filter(pk=self.edge.pk).exists())

    def test_edge_khong_ton_tai_tra_404(self):
        response = self.client.delete(reverse("edge-admin-edge-detail", args=[999999]))
        self.assertEqual(response.status_code, 404)


class IssueKeyTest(TestCase):
    def setUp(self):
        self.admin = make_user("quan-tri-cap-khoa", roles.ADMIN)
        self.edge = Edge.objects.create(label="Máy B")
        self.client.force_login(self.admin)

    def test_cap_khoa_tra_ve_khoa_tho_DUNG_MOT_LAN(self):
        response = self.client.post(
            reverse("edge-admin-issue-key", args=[self.edge.pk]),
            {"name": "Đợt tháng 9"}, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["api_key"])
        self.assertEqual(len(body["api_key"]), len(body["api_key"].strip()))

    def test_xem_lai_Edge_KHONG_co_khoa_tho(self):
        """Đây là bài quan trọng nhất của cả module: lộ khoá lần hai là một lỗ hổng."""
        self.client.post(reverse("edge-admin-issue-key", args=[self.edge.pk]),
                         {}, content_type="application/json")
        body = self.client.get(reverse("edge-admin-edges")).json()
        row = next(r for r in body["results"] if r["id"] == self.edge.pk)
        for key_row in row["api_keys"]:
            self.assertNotIn("api_key", key_row)

    def test_mot_Edge_co_nhieu_khoa_cung_luc(self):
        """Xoay khoá không downtime: cấp khoá mới trước, thu hồi khoá cũ sau."""
        self.client.post(reverse("edge-admin-issue-key", args=[self.edge.pk]),
                         {}, content_type="application/json")
        self.client.post(reverse("edge-admin-issue-key", args=[self.edge.pk]),
                         {}, content_type="application/json")
        self.assertEqual(EdgeApiKey.objects.filter(edge=self.edge).count(), 2)

    def test_khoa_cap_ra_XAC_THUC_DUOC_that(self):
        """Đường vòng thật: khoá cấp qua API này phải dùng gọi /edge/sync/ được."""
        raw_key = self.client.post(
            reverse("edge-admin-issue-key", args=[self.edge.pk]),
            {}, content_type="application/json").json()["api_key"]

        response = self.client.get(
            reverse("edge-health"),
            HTTP_AUTHORIZATION=f"Bearer {raw_key}", HTTP_X_EDGE_ID="tam")
        self.assertNotEqual(response.status_code, 401)

    def test_van_hanh_edge_khong_cap_duoc_khoa(self):
        self.client.force_login(make_user("van-hanh-cap-khoa", roles.EDGE_OPERATOR))
        response = self.client.post(
            reverse("edge-admin-issue-key", args=[self.edge.pk]),
            {}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_edge_khong_ton_tai_tra_404(self):
        response = self.client.post(
            reverse("edge-admin-issue-key", args=[999999]),
            {}, content_type="application/json")
        self.assertEqual(response.status_code, 404)


class RevokeKeyTest(TestCase):
    def setUp(self):
        self.admin = make_user("quan-tri-thu-hoi", roles.ADMIN)
        self.edge = Edge.objects.create(label="Máy C")
        self.record, self.raw_key = EdgeApiKey.issue(self.edge)
        self.client.force_login(self.admin)

    def test_thu_hoi_co_hieu_luc_ngay(self):
        response = self.client.post(
            reverse("edge-admin-revoke-key", args=[self.record.pk]))
        self.assertEqual(response.status_code, 200)
        self.record.refresh_from_db()
        self.assertFalse(self.record.is_active)

    def test_khoa_da_thu_hoi_khong_con_xac_thuc_duoc(self):
        self.client.post(reverse("edge-admin-revoke-key", args=[self.record.pk]))
        response = self.client.post(
            reverse("edge-sync"), {"edge_id": "e1", "records": []},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_key}", HTTP_X_EDGE_ID="e1")
        self.assertEqual(response.status_code, 401)

    def test_khong_xoa_ban_ghi_chi_thu_hoi(self):
        """Xoá là mất bằng chứng; thu hồi vẫn giữ được lịch sử ai đã cấp/dùng khoá."""
        self.client.post(reverse("edge-admin-revoke-key", args=[self.record.pk]))
        self.assertTrue(EdgeApiKey.objects.filter(pk=self.record.pk).exists())

    def test_van_hanh_edge_khong_thu_hoi_duoc(self):
        self.client.force_login(make_user("van-hanh-thu-hoi", roles.EDGE_OPERATOR))
        response = self.client.post(
            reverse("edge-admin-revoke-key", args=[self.record.pk]))
        self.assertEqual(response.status_code, 403)


class LegacyEdgeListUnchangedTest(TestCase):
    """`hub/edges/` không được đổi khuôn — Data.tsx đang phụ thuộc đúng hình dạng cũ."""

    def test_khuon_du_lieu_khong_doi(self):
        Edge.objects.create(label="Máy cũ", is_active=True)
        self.client.force_login(make_user("van-hanh-legacy", roles.EDGE_OPERATOR))
        row = self.client.get(reverse("hub-edges")).json()["results"][0]
        for field in ("id", "label", "edge_id", "hostname", "app_version",
                     "is_active", "registered_at", "last_seen_at", "record_count"):
            self.assertIn(field, row)
        self.assertNotIn("api_keys", row,
                         "Thêm api_keys vào đây sẽ phá khuôn mà Data.tsx đang đọc")
