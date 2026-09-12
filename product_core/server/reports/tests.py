# -*- coding: utf-8 -*-
"""Vận hành & báo cáo (Master Plan mục 15).

Hai điều bài này canh kỹ nhất:

1. **Overview không tính lại logic của chỗ khác** — chỉ gọi và gộp. Test không
   kiểm tra công thức tính chỉ số (đã có ở `hiring/tests.py`, `rb/tests.py`);
   chỉ kiểm tra `overview()` có gọi đúng và gộp đúng.
2. **Quyền của trang vận hành khác quyền của bộ lọc đã lưu.** Trang vận hành
   gộp cả số Talent lẫn RB — chỉ Admin/Manager. Bộ lọc đã lưu là tiện ích cá
   nhân — recruiter lưu bộ lọc Talent không cần vào được trang vận hành.
"""
import json

from accounts import roles
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import FilterHistory, SavedView


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class OverviewTest(TestCase):
    def setUp(self):
        self.client.force_login(make_user("quanly", roles.MANAGER))

    def test_gop_du_nam_khoi(self):
        body = self.client.get(reverse("reports-overview")).json()
        for khoi in ("sync", "ai_usage", "agents", "talent", "rb"):
            self.assertIn(khoi, body)

    def test_chua_co_agent_run_nao_thi_None_khong_phai_0(self):
        """Cùng nguyên tắc `hiring/metrics.py`: chưa đủ dữ liệu phải nói rõ,
        không giả vờ bằng 0."""
        body = self.client.get(reverse("reports-overview")).json()
        self.assertEqual(body["agents"]["total_runs"], 0)
        self.assertIsNone(body["agents"]["error_rate"])

    def test_co_agent_run_thi_tinh_dung(self):
        from agents import runtime
        from agents.models import AGENT_TALENT

        with runtime.run(AGENT_TALENT, goal="x") as run:
            run.finish()
        with runtime.run(AGENT_TALENT, goal="y"):
            pass                     # lỗi giữa chừng không nắm, coi như OK

        body = self.client.get(reverse("reports-overview")).json()
        self.assertEqual(body["agents"]["total_runs"], 2)
        self.assertEqual(body["agents"]["error_rate"], 0.0)


class OverviewPermissionTest(TestCase):
    def test_recruiter_KHONG_vao_duoc_trang_van_hanh(self):
        """Trang này gộp cả số RB — cho Recruiter thấy là lộ dữ liệu ngoài
        nghiệp vụ của họ."""
        self.client.force_login(make_user("tuyendung", roles.RECRUITER))
        self.assertEqual(self.client.get(reverse("reports-overview")).status_code, 403)

    def test_rb_sales_KHONG_vao_duoc(self):
        self.client.force_login(make_user("sales", roles.RB_SALES))
        self.assertEqual(self.client.get(reverse("reports-overview")).status_code, 403)

    def test_manager_vao_duoc(self):
        self.client.force_login(make_user("quanly", roles.MANAGER))
        self.assertEqual(self.client.get(reverse("reports-overview")).status_code, 200)

    def test_admin_vao_duoc(self):
        self.client.force_login(make_user("admin", roles.ADMIN))
        self.assertEqual(self.client.get(reverse("reports-overview")).status_code, 200)

    def test_chua_dang_nhap_bi_chan(self):
        self.assertIn(self.client.get(reverse("reports-overview")).status_code,
                      (401, 403))


class SavedViewTest(TestCase):
    def setUp(self):
        self.recruiter = make_user("tuyendung", roles.RECRUITER)
        self.client.force_login(self.recruiter)

    def _post(self, body):
        return self.client.post(reverse("reports-saved-views"),
                                data=json.dumps(body), content_type="application/json")

    def test_luu_bo_loc_KHONG_can_quyen_trang_van_hanh(self):
        """Recruiter không vào được /reports/overview/ nhưng vẫn lưu được bộ
        lọc Talent — hai quyền khác nhau."""
        response = self._post({"module": "talent", "name": "SQL Hà Nội",
                               "filters": {"skills": "SQL", "location": "Hà Nội"}})
        self.assertEqual(response.status_code, 201)

    def test_khong_luu_duoc_bo_loc_module_khong_co_quyen(self):
        """Recruiter không có quyền RB — không lưu được bộ lọc RB."""
        response = self._post({"module": "rb", "name": "X", "filters": {}})
        self.assertEqual(response.status_code, 403)

    def test_module_la_thi_400(self):
        response = self._post({"module": "khong_ton_tai", "name": "X"})
        self.assertEqual(response.status_code, 400)

    def test_thieu_ten_thi_400(self):
        response = self._post({"module": "talent", "filters": {}})
        self.assertEqual(response.status_code, 400)

    def test_luu_TRUNG_ten_thi_GHI_DE_khong_tao_them(self):
        for _ in range(2):
            self._post({"module": "talent", "name": "SQL Hà Nội",
                       "filters": {"skills": "SQL"}})
        self.assertEqual(SavedView.objects.count(), 1)

    def test_danh_sach_chi_thay_cua_CHINH_MINH(self):
        khac = make_user("nguoi_khac", roles.RECRUITER)
        SavedView.objects.create(owner=khac, module="talent", name="Của người khác")
        self._post({"module": "talent", "name": "Của tôi", "filters": {}})

        body = self.client.get(reverse("reports-saved-views")).json()
        names = [row["name"] for row in body["results"]]
        self.assertEqual(names, ["Của tôi"])

    def test_loc_theo_module(self):
        self._post({"module": "talent", "name": "A", "filters": {}})
        self.client.force_login(make_user("rm", roles.RB_SALES))
        self._post({"module": "rb", "name": "B", "filters": {}})

        body = self.client.get(reverse("reports-saved-views"), {"module": "rb"}).json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["name"], "B")

    def test_khong_xoa_duoc_bo_loc_cua_NGUOI_KHAC(self):
        khac = make_user("nguoi_khac", roles.RECRUITER)
        view = SavedView.objects.create(owner=khac, module="talent", name="X")
        response = self.client.delete(reverse("reports-saved-view", args=[view.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(SavedView.objects.filter(pk=view.pk).exists())

    def test_xoa_bo_loc_cua_minh(self):
        response = self._post({"module": "talent", "name": "X", "filters": {}})
        view_id = response.json()["id"]
        response = self.client.delete(reverse("reports-saved-view", args=[view_id]))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(SavedView.objects.filter(pk=view_id).exists())

    def test_mo_lai_view_cap_nhat_last_used_at(self):
        response = self._post({"module": "talent", "name": "X", "filters": {}})
        view_id = response.json()["id"]
        self.assertIsNone(SavedView.objects.get(pk=view_id).last_used_at)

        self.client.post(reverse("reports-saved-view", args=[view_id]))
        self.assertIsNotNone(SavedView.objects.get(pk=view_id).last_used_at)


class FilterHistoryTest(TestCase):
    def setUp(self):
        self.recruiter = make_user("history-recruiter", roles.RECRUITER)
        self.client.force_login(self.recruiter)
        self.url = reverse("reports-filter-history")

    def _post(self, filters):
        return self.client.post(self.url, data=json.dumps({
            "module": "talent", "filters": filters,
        }), content_type="application/json")

    def test_ghi_lai_cung_bo_loc_khong_tao_ban_ghi_trung(self):
        self.assertEqual(self._post({"skills": "SQL", "location": "Hà Nội"}).status_code, 201)
        self.assertEqual(self._post({"location": "Hà Nội", "skills": "SQL"}).status_code, 201)
        self.assertEqual(FilterHistory.objects.count(), 1)

    def test_chi_hien_lich_su_cua_chinh_nguoi_dung(self):
        self._post({"skills": "Python"})
        other = make_user("history-other", roles.RECRUITER)
        FilterHistory.objects.create(owner=other, module="talent", signature="x",
                                     filters={"skills": "Java"})
        response = self.client.get(self.url, {"module": "talent"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["filters"] for row in response.json()["results"]],
                         [{"skills": "Python"}])

    def test_xoa_lich_su_cua_module(self):
        self._post({"skills": "Python"})
        self.assertEqual(self.client.delete(f"{self.url}?module=talent").status_code, 204)
        self.assertFalse(FilterHistory.objects.filter(owner=self.recruiter).exists())
