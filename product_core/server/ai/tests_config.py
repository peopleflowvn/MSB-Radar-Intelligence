# -*- coding: utf-8 -*-
"""Kiểm thử trang cấu hình nhà cung cấp AI.

Trọng tâm: **khoá API không được rò ra ngoài** — không qua API, không qua bản
dump CSDL. Và cấu hình sửa trên giao diện phải có hiệu lực ngay, không cần khởi
động lại.
"""
import json
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Edge, EdgeApiKey
from accounts import roles

from . import crypto
from .models import LLMCall, ProviderConfig
from .providers import OpenAICompatibleProvider
from .router import Router, reset_router
from .tests import fake_transport


def make_admin(username="quantri"):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-rat-dai-123")
    user.groups.add(Group.objects.get(name=roles.ADMIN))
    return user


class CryptoTest(TestCase):
    def test_ma_hoa_roi_giai_ma_lai_dung(self):
        self.assertEqual(crypto.decrypt(crypto.encrypt("sk-bi-mat-123")), "sk-bi-mat-123")

    def test_ban_ma_khong_chua_khoa_goc(self):
        self.assertNotIn("sk-bi-mat-123", crypto.encrypt("sk-bi-mat-123"))

    def test_moi_lan_ma_hoa_ra_ban_ma_khac(self):
        """Fernet có IV ngẫu nhiên: hai khoá giống nhau không lộ ra là giống nhau."""
        self.assertNotEqual(crypto.encrypt("abc"), crypto.encrypt("abc"))

    def test_chuoi_rong_van_la_chuoi_rong(self):
        self.assertEqual(crypto.encrypt(""), "")
        self.assertEqual(crypto.decrypt(""), "")

    def test_doi_secret_key_thi_khong_giai_ma_duoc(self):
        token = crypto.encrypt("sk-bi-mat")
        with override_settings(SECRET_KEY="mot-khoa-hoan-toan-khac"):
            with self.assertRaises(crypto.DecryptError):
                crypto.decrypt(token)

    def test_mask_giu_dau_va_che_phan_con_lai(self):
        masked = crypto.mask("sk-abcdef1234567890")
        self.assertTrue(masked.startswith("sk-abc"))
        self.assertNotIn("1234567890", masked)

    def test_mask_khoa_rat_ngan_che_het(self):
        self.assertEqual(crypto.mask("abc"), "•••")


class ProviderConfigModelTest(TestCase):
    def setUp(self):
        self.config = ProviderConfig.objects.create(provider=ProviderConfig.DEEPSEEK)

    def test_khoa_khong_luu_dang_ro(self):
        self.config.set_api_key("sk-bi-mat-123")
        self.config.save()
        row = ProviderConfig.objects.get(pk=self.config.pk)
        self.assertNotIn("sk-bi-mat-123", row.api_key_encrypted)
        self.assertEqual(row.get_api_key(), "sk-bi-mat-123")

    def test_hint_khong_chua_du_khoa(self):
        self.config.set_api_key("sk-abcdef1234567890")
        self.assertNotIn("1234567890", self.config.api_key_hint)

    def test_xoa_khoa_bang_chuoi_rong(self):
        self.config.set_api_key("sk-x")
        self.config.set_api_key("")
        self.assertFalse(self.config.has_api_key)
        self.assertEqual(self.config.api_key_hint, "")

    def test_khoa_khong_giai_ma_duoc_thi_bao_can_nhap_lai(self):
        self.config.set_api_key("sk-x")
        self.config.save()
        with override_settings(SECRET_KEY="khoa-khac-hoan-toan"):
            row = ProviderConfig.objects.get(pk=self.config.pk)
            self.assertTrue(row.has_api_key)
            self.assertFalse(row.key_readable, "phải báo là cần nhập lại")
            self.assertEqual(row.get_api_key(), "", "không được ném lỗi ra ngoài")


class RouterDbConfigTest(TestCase):
    def setUp(self):
        reset_router()
        self.addCleanup(reset_router)

    def test_csdl_thang_bien_moi_truong(self):
        """Người vận hành phải đổi được mà không cần khởi động lại container."""
        config = ProviderConfig.objects.create(
            provider=ProviderConfig.OPENAI, enabled=True, priority=10,
            model="model-tu-giao-dien")
        config.set_api_key("khoa-tu-giao-dien")
        config.save()

        router = Router(env={"MSB_AI_OPENAI_API_KEY": "khoa-tu-env",
                             "MSB_AI_OPENAI_MODEL": "model-tu-env"},
                        transport=fake_transport())
        provider = router.get_provider("openai")
        self.assertEqual(provider.model, "model-tu-giao-dien")
        self.assertEqual(provider.api_key, "khoa-tu-giao-dien")

    def test_thu_tu_uu_tien_lay_tu_csdl(self):
        for name, priority in (("deepseek", 10), ("gemini", 20)):
            ProviderConfig.objects.create(provider=name, enabled=True, priority=priority)
        self.assertEqual(Router(env={}).provider_order(), ["deepseek", "gemini"])

    def test_nha_cung_cap_bi_tat_khong_duoc_thu(self):
        ProviderConfig.objects.create(provider="openai", enabled=True, priority=10)
        ProviderConfig.objects.create(provider="deepseek", enabled=False, priority=5)
        self.assertEqual(Router(env={}).provider_order(), ["openai"])

    def test_chua_cau_hinh_gi_trong_csdl_thi_dung_bien_moi_truong(self):
        order = Router(env={"MSB_AI_PROVIDER_DEFAULT": "gemini"}).provider_order()
        self.assertEqual(order[0], "gemini")

    def test_csdl_thieu_khoa_thi_lui_ve_bien_moi_truong(self):
        """Bật một nhà cung cấp trên giao diện nhưng chưa nhập khoá."""
        ProviderConfig.objects.create(provider="openai", enabled=True, priority=10)
        router = Router(env={"MSB_AI_OPENAI_API_KEY": "khoa-env"},
                        transport=fake_transport())
        self.assertEqual(router.get_provider("openai").api_key, "khoa-env")

    def test_base_url_de_trong_thi_dung_mac_dinh(self):
        config = ProviderConfig.objects.create(provider="greennode", enabled=True,
                                               model="m")
        config.set_api_key("k")
        config.save()
        provider = Router(env={}).get_provider("greennode")
        self.assertIn("vngcloud.vn", provider.base_url)


class SettingsApiTest(TestCase):
    def setUp(self):
        reset_router()
        self.addCleanup(reset_router)
        self.user = make_admin()
        self.client.force_login(self.user)

    def _patch(self, provider, body):
        return self.client.patch(
            reverse("ai-provider-update", args=[provider]),
            data=json.dumps(body), content_type="application/json")

    def test_danh_sach_hien_du_bon_nha_cung_cap(self):
        body = self.client.get(reverse("ai-providers")).json()
        self.assertEqual({r["provider"] for r in body["results"]},
                         {"greennode", "openai", "gemini", "deepseek"})

    def test_danh_sach_kem_mac_dinh_de_nguoi_dung_biet_dien_gi(self):
        rows = {r["provider"]: r for r in self.client.get(reverse("ai-providers")).json()["results"]}
        self.assertIn("vngcloud.vn", rows["greennode"]["base_url_default"])
        self.assertEqual(rows["deepseek"]["model_default"], "deepseek-v4-flash")

    def test_greennode_uu_tien_cao_nhat_mac_dinh(self):
        rows = {r["provider"]: r for r in self.client.get(reverse("ai-providers")).json()["results"]}
        self.assertLess(rows["greennode"]["priority"], rows["openai"]["priority"])

    # ---------- khoá không được rò ----------

    def test_API_KHONG_BAO_GIO_TRA_KHOA_DAY_DU(self):
        self._patch("deepseek", {"api_key": "sk-bi-mat-tuyet-doi-123456"})
        raw = self.client.get(reverse("ai-providers")).content.decode("utf-8")
        self.assertNotIn("sk-bi-mat-tuyet-doi-123456", raw)
        self.assertNotIn("bi-mat-tuyet-doi", raw)

    def test_chi_tra_ve_dang_che(self):
        self._patch("deepseek", {"api_key": "sk-abcdefghijklmnop"})
        row = [r for r in self.client.get(reverse("ai-providers")).json()["results"]
               if r["provider"] == "deepseek"][0]
        self.assertTrue(row["has_api_key"])
        self.assertTrue(row["api_key_hint"].startswith("sk-abc"))
        self.assertNotIn("ijklmnop", row["api_key_hint"])

    def test_luu_form_khong_gui_khoa_thi_KHONG_xoa_khoa_dang_dung(self):
        """Lỗi kinh điển: lưu form bình thường lại xoá mất khoá."""
        self._patch("deepseek", {"api_key": "sk-dang-dung"})
        self._patch("deepseek", {"model": "model-moi"})
        config = ProviderConfig.objects.get(provider="deepseek")
        self.assertEqual(config.get_api_key(), "sk-dang-dung")
        self.assertEqual(config.model, "model-moi")

    def test_gui_khoa_rong_thi_xoa_khoa(self):
        self._patch("deepseek", {"api_key": "sk-x"})
        self._patch("deepseek", {"api_key": ""})
        self.assertFalse(ProviderConfig.objects.get(provider="deepseek").has_api_key)

    # ---------- sửa cấu hình ----------

    def test_sua_duoc_cac_truong(self):
        response = self._patch("greennode", {
            "enabled": True, "priority": 5, "model": "m-tu-workshop",
            "base_url": "https://noi-khac/v1", "timeout": 90})
        self.assertEqual(response.status_code, 200)
        config = ProviderConfig.objects.get(provider="greennode")
        self.assertTrue(config.enabled)
        self.assertEqual(config.priority, 5)
        self.assertEqual(config.model, "m-tu-workshop")
        self.assertEqual(config.timeout, 90)

    def test_ghi_nhan_ai_sua(self):
        self._patch("openai", {"model": "m"})
        self.assertEqual(ProviderConfig.objects.get(provider="openai").updated_by, "quantri")

    def test_doi_khoa_thi_xoa_ket_qua_kiem_tra_cu(self):
        """Kết quả kiểm tra của khoá cũ không nói gì về khoá mới."""
        config = ProviderConfig.objects.create(provider="gemini")
        config.last_check_ok = True
        config.save()
        self._patch("gemini", {"api_key": "sk-moi"})
        config.refresh_from_db()
        self.assertIsNone(config.last_check_ok)

    def test_nha_cung_cap_la_thi_404(self):
        self.assertEqual(self._patch("khong-ton-tai", {"model": "m"}).status_code, 404)

    def test_gia_tri_sai_thi_400(self):
        self.assertEqual(self._patch("openai", {"timeout": -5}).status_code, 400)

    def test_sua_xong_co_hieu_luc_ngay(self):
        """Router nhớ nhà cung cấp đã dựng; không xoá thì thay đổi chưa ăn."""
        self._patch("deepseek", {"enabled": True, "priority": 1, "api_key": "k",
                                 "model": "m"})
        self.assertEqual(get_order()[0], "deepseek")
        self._patch("deepseek", {"enabled": False})
        self.assertNotIn("deepseek", get_order())

    # ---------- quyền ----------

    def test_chua_dang_nhap_thi_bi_chan(self):
        self.client.logout()
        for name, args in (("ai-providers", []), ("ai-usage", [])):
            self.assertIn(self.client.get(reverse(name, args=args)).status_code, (401, 403))

    def test_khoa_edge_khong_mo_duoc_trang_cai_dat(self):
        """Edge là máy thu thập dữ liệu, không có việc gì với cấu hình AI."""
        self.client.logout()
        edge = Edge.objects.create(label="Máy TA")
        _, raw = EdgeApiKey.issue(edge)
        response = self.client.get(reverse("ai-providers"),
                                   HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertIn(response.status_code, (401, 403))


def get_order():
    from .router import get_router
    return get_router().provider_order()


class UsageApiTest(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.client.force_login(self.user)
        LLMCall.objects.create(provider="greennode", model="m", prompt_tokens=100,
                               completion_tokens=50)
        LLMCall.objects.create(provider="greennode", model="m", prompt_tokens=10,
                               completion_tokens=5)
        LLMCall.objects.create(provider="openai", model="m", ok=False, error="hỏng")

    def test_thong_ke_theo_nha_cung_cap(self):
        body = self.client.get(reverse("ai-usage")).json()
        self.assertEqual(body["total_calls"], 3)
        self.assertEqual(body["failed_calls"], 1)
        greennode = [r for r in body["by_provider"] if r["provider"] == "greennode"][0]
        self.assertEqual(greennode["calls"], 2)
        self.assertEqual(greennode["total_tokens"], 165)

    def test_thong_ke_tach_theo_tung_mo_hinh_ai(self):
        LLMCall.objects.create(provider="greennode", model="z-ai/glm-5.2-hackathon", prompt_tokens=200,
                               completion_tokens=100)
        LLMCall.objects.create(provider="greennode", model="qwen/qwen-2.5-72b", prompt_tokens=50,
                               completion_tokens=25)
        LLMCall.objects.create(provider="gemini", model="gemini-2.5-flash", prompt_tokens=80,
                               completion_tokens=40)
        LLMCall.objects.create(provider="gemini", model="gemini-1.5-pro", prompt_tokens=300,
                               completion_tokens=150)

        body = self.client.get(reverse("ai-usage")).json()
        self.assertIn("by_model", body)
        models_map = {(r["provider"], r["model"]): r for r in body["by_model"]}

        self.assertIn(("greennode", "z-ai/glm-5.2-hackathon"), models_map)
        self.assertEqual(models_map[("greennode", "z-ai/glm-5.2-hackathon")]["total_tokens"], 300)

        self.assertIn(("greennode", "qwen/qwen-2.5-72b"), models_map)
        self.assertEqual(models_map[("greennode", "qwen/qwen-2.5-72b")]["total_tokens"], 75)

        self.assertIn(("gemini", "gemini-2.5-flash"), models_map)
        self.assertEqual(models_map[("gemini", "gemini-2.5-flash")]["total_tokens"], 120)

        self.assertIn(("gemini", "gemini-1.5-pro"), models_map)
        self.assertEqual(models_map[("gemini", "gemini-1.5-pro")]["total_tokens"], 450)

        # Kiểm tra danh sách models lồng trong by_provider
        greennode_row = [r for r in body["by_provider"] if r["provider"] == "greennode"][0]
        gn_models = {m["model"]: m for m in greennode_row["models"]}
        self.assertIn("z-ai/glm-5.2-hackathon", gn_models)
        self.assertIn("qwen/qwen-2.5-72b", gn_models)


class ProviderTestEndpointTest(TestCase):
    def setUp(self):
        reset_router()
        self.addCleanup(reset_router)
        self.user = make_admin()
        self.client.force_login(self.user)

    def test_chua_co_khoa_thi_bao_ro_rang(self):
        ProviderConfig.objects.create(provider="deepseek", model="m")
        response = self.client.post(reverse("ai-provider-test", args=["deepseek"]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Chưa nhập khoá", response.json()["detail"])

    def test_khoa_hong_thi_bao_nhap_lai(self):
        """Làm hỏng bản mã trực tiếp thay vì đổi SECRET_KEY.

        Đổi SECRET_KEY trong test cũng làm vô hiệu chữ ký cookie phiên, nên
        request sau đó trả 401 và ta kiểm tra nhầm thứ.
        """
        config = ProviderConfig.objects.create(provider="deepseek", model="m")
        config.set_api_key("k")
        config.api_key_encrypted = "ban-ma-hong-khong-doc-duoc"
        config.save()

        response = self.client.post(reverse("ai-provider-test", args=["deepseek"]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("nhập lại", response.json()["detail"])

    def test_ket_qua_kiem_tra_duoc_luu_lai(self):
        ProviderConfig.objects.create(provider="deepseek", model="m")
        self.client.post(reverse("ai-provider-test", args=["deepseek"]))
        config = ProviderConfig.objects.get(provider="deepseek")
        self.assertIsNotNone(config.last_checked_at)
        self.assertFalse(config.last_check_ok)


class ProviderTestPerKeyTest(TestCase):
    """Nút "Kiểm tra kết nối" phải nói rõ khoá NÀO hỏng.

    Với sáu khoá, "có gì đó hỏng" là câu vô dụng: người vận hành không biết đi
    thay khoá nào, và một khoá hỏng sẽ vô hình cho tới lúc nó tình cờ được xoay
    tới — thường là giữa buổi demo.
    """

    def setUp(self):
        reset_router()
        self.addCleanup(reset_router)
        self.user = make_admin()
        self.client.force_login(self.user)

        self.config = ProviderConfig.objects.create(
            provider="deepseek", model="m", base_url="https://x/v1")
        self.config.set_api_key("khoa-tot-1, khoa-hong, khoa-tot-2")
        self.config.save()

    def _test_endpoint(self, transport):
        with mock.patch("ai.views.OpenAICompatibleProvider",
                        side_effect=self._factory(transport)):
            return self.client.post(reverse("ai-provider-test", args=["deepseek"]))

    @staticmethod
    def _factory(transport):
        def build(**kwargs):
            kwargs["transport"] = transport
            return OpenAICompatibleProvider(**kwargs)
        return build

    @staticmethod
    def _transport(bad_key="khoa-hong"):
        def transport(url, headers, body, timeout):
            if bad_key in headers.get("Authorization", ""):
                return 401, {"error": {"message": "khoá sai"}}
            return 200, {"choices": [{"message": {"content": "ok"}}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        return transport

    def test_thu_TUNG_khoa_mot(self):
        body = self._test_endpoint(self._transport()).json()
        self.assertEqual(len(body["keys"]), 3)
        self.assertEqual([k["ok"] for k in body["keys"]], [True, False, True])

    def test_noi_ro_khoa_nao_hong(self):
        body = self._test_endpoint(self._transport()).json()
        self.assertIn("2/3 khoá dùng được", body["detail"])
        hong = next(k for k in body["keys"] if not k["ok"])
        self.assertIn("khoa-hon", hong["label"])

    def test_mot_khoa_hong_KHONG_lam_ca_cum_bi_danh_dau_hong(self):
        """Đánh dấu hỏng cả cụm sẽ khiến người vận hành tắt nhầm nhà cung cấp
        vẫn đang chạy tốt bằng những khoá còn lại."""
        response = self._test_endpoint(self._transport())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(ProviderConfig.objects.get(provider="deepseek").last_check_ok)

    def test_moi_khoa_deu_hong_thi_bao_400(self):
        response = self._test_endpoint(self._transport(bad_key="khoa"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Không khoá nào dùng được", response.json()["detail"])

    def test_khoa_khong_bao_gio_ve_trinh_duyet_o_dang_day_du(self):
        """Quy tắc xuyên suốt của trang này."""
        body = self._test_endpoint(self._transport()).json()
        for item in body["keys"]:
            self.assertNotIn("khoa-tot-1", item["label"])
            self.assertIn("…", item["label"])
