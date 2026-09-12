# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import time
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from . import roles
from .models import (AuthenticationEvent, EmailLoginCode, EmailOtpSettings,
                     ResendWebhookEvent, UserLoginPolicy)


class EmailOtpLoginTest(TestCase):
    def setUp(self):
        roles.ensure_groups()
        self.user = User.objects.create_user("tunglh2@tntalent.vn", email="tunglh2@tntalent.vn")
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        UserLoginPolicy.objects.create(user=self.user, login_type=UserLoginPolicy.TNTALENT)
        self.config = EmailOtpSettings.current()
        self.config.set_api_key("re_test_key")
        self.config.from_email = "radar@example.com"
        self.config.enabled = True
        self.config.save()

    def test_public_config_chi_bat_khi_resend_san_sang(self):
        body = self.client.get(reverse("login-options")).json()
        self.assertTrue(body["local_login_enabled"])
        self.assertEqual(body["email_otp"], {"tntalent": True, "msb": True})
        self.assertEqual(body["email_otp_domains"]["tntalent"], ["tntalent.vn"])

    def test_domain_legacy_bi_stringify_nhieu_lop_van_duoc_doc_dung(self):
        self.config.tntalent_domains = "['\\\"[\\\\\\\'tntalent.vn\\\\\\\']\\\"']"
        self.config.save(update_fields=["tntalent_domains"])
        body = self.client.get(reverse("login-options")).json()
        self.assertEqual(body["email_otp_domains"]["tntalent"], ["tntalent.vn"])
        response = self.client.post(reverse("login-discovery"), {"identifier": self.user.username},
                                    format="json", REMOTE_ADDR="198.18.0.31")
        self.assertEqual(response.json(), {"mode": "otp", "realm": "tntalent"})

    def test_discovery_chan_tai_khoan_khong_ton_tai_va_tra_dung_luong(self):
        missing = self.client.post(reverse("login-discovery"), {"identifier": "khongco@tntalent.vn"}, format="json",
                                   REMOTE_ADDR="198.18.0.11")
        self.assertEqual(missing.status_code, 404)
        otp = self.client.post(reverse("login-discovery"), {"identifier": "tunglh2@tntalent.vn"}, format="json",
                               REMOTE_ADDR="198.18.0.12")
        self.assertEqual(otp.json(), {"mode": "otp", "realm": "tntalent"})
        local = User.objects.create_user("local@example.com", email="local@example.com")
        UserLoginPolicy.objects.create(user=local, login_type=UserLoginPolicy.LOCAL)
        local_response = self.client.post(reverse("login-discovery"), {"identifier": "local@example.com"}, format="json",
                                          REMOTE_ADDR="198.18.0.13")
        self.assertEqual(local_response.json(), {"mode": "local"})

        # User local có email domain công ty và username không có @ vẫn vào mode local
        local_admin = User.objects.create_user("admin_local", email="admin_local@tntalent.vn", password="secret_password_123")
        UserLoginPolicy.objects.create(user=local_admin, login_type=UserLoginPolicy.LOCAL)
        admin_response = self.client.post(reverse("login-discovery"), {"identifier": "admin_local"}, format="json",
                                          REMOTE_ADDR="198.18.0.14")
        self.assertEqual(admin_response.json(), {"mode": "local"})
        login_res = self.client.post(reverse("auth-login"), {"username": "admin_local", "password": "secret_password_123"}, format="json")
        self.assertEqual(login_res.status_code, 200)

    @mock.patch("accounts.email_otp._send_resend")
    def test_tai_khoan_domain_otp_cu_khong_co_policy_van_gui_otp(self, sender):
        legacy = User.objects.create_user("legacy@tntalent.vn", email="legacy@tntalent.vn")
        response = self.client.post(reverse("login-discovery"), {"identifier": legacy.username}, format="json",
                                    REMOTE_ADDR="198.18.0.21")
        self.assertEqual(response.json(), {"mode": "otp", "realm": "tntalent"})
        self.assertEqual(UserLoginPolicy.objects.get(user=legacy).login_type, UserLoginPolicy.TNTALENT)
        response = self.client.post(reverse("email-otp-request", args=["tntalent"]),
                                    {"identifier": legacy.username}, format="json")
        self.assertEqual(response.status_code, 200)
        sender.assert_called_once()

    @mock.patch("accounts.email_otp._send_resend")
    @mock.patch("accounts.email_otp.secrets.randbelow", return_value=123456)
    def test_gui_va_xac_thuc_otp_tao_session(self, _random, sender):
        response = self.client.post(reverse("email-otp-request", args=["tntalent"]),
                                    {"identifier": "tunglh2@tntalent.vn"}, format="json")
        self.assertEqual(response.status_code, 200)
        sender.assert_called_once()
        self.assertEqual(EmailLoginCode.objects.count(), 1)
        response = self.client.post(reverse("email-otp-verify", args=["tntalent"]),
                                    {"identifier": "tunglh2@tntalent.vn", "code": "123456"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get(reverse("auth-me")).json()["authenticated"])
        self.assertEqual(AuthenticationEvent.objects.filter(result="email_otp_login_success").count(), 1)

    def test_send_resend_dat_user_agent_rieng_de_khong_bi_cloudflare_chan(self):
        # Cloudflare trước api.resend.com trả 403 ("error code: 1010") cho
        # User-Agent mặc định "Python-urllib/x.y". Request phải mang UA riêng.
        captured = {}

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def _fake_urlopen(request, timeout=None):
            captured["ua"] = request.get_header("User-agent")
            return _Resp()

        with mock.patch("accounts.email_otp.urlopen", _fake_urlopen):
            response = self.client.post(reverse("email-otp-request", args=["tntalent"]),
                                        {"identifier": "tunglh2@tntalent.vn"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(captured["ua"])
        self.assertNotIn("python-urllib", captured["ua"].lower())

    @mock.patch("accounts.email_otp._send_resend")
    def test_sai_realm_khong_gui_email(self, sender):
        response = self.client.post(reverse("email-otp-request", args=["msb"]),
                                    {"identifier": "tunglh2@tntalent.vn"}, format="json")
        self.assertEqual(response.status_code, 200)
        sender.assert_not_called()

    @mock.patch("accounts.email_otp._send_resend")
    def test_domain_khong_duoc_admin_cho_phep_khong_gui_email(self, sender):
        self.user.username = "tunglh2@ngoai-domain.vn"
        self.user.email = "tunglh2@ngoai-domain.vn"
        self.user.save(update_fields=["username", "email"])
        response = self.client.post(reverse("email-otp-request", args=["tntalent"]),
                                    {"identifier": "tunglh2@ngoai-domain.vn"}, format="json")
        self.assertEqual(response.status_code, 200)
        sender.assert_not_called()

    @mock.patch("accounts.email_otp._send_resend")
    def test_ma_sai_bi_chan_sau_so_lan_gioi_han(self, sender):
        self.config.max_attempts = 3
        self.config.save(update_fields=["max_attempts"])
        self.client.post(reverse("email-otp-request", args=["tntalent"]),
                         {"identifier": "tunglh2@tntalent.vn"}, format="json")
        for _ in range(3):
            response = self.client.post(reverse("email-otp-verify", args=["tntalent"]),
                                        {"identifier": "tunglh2@tntalent.vn", "code": "000000"}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertIsNotNone(EmailLoginCode.objects.get().used_at)

    @mock.patch("accounts.email_otp._send_resend")
    @mock.patch("accounts.email_otp.secrets.randbelow", return_value=654321)
    def test_local_quen_mat_khau_dat_lai_bang_otp_email(self, _random, sender):
        local = User.objects.create_user("local@example.com", email="local@example.com",
                                         password="mat-khau-cu-dai")
        UserLoginPolicy.objects.create(user=local, login_type=UserLoginPolicy.LOCAL)
        response = self.client.post(reverse("local-reset-request"), {"identifier": "local@example.com"}, format="json")
        self.assertEqual(response.status_code, 200)
        sender.assert_called_once()
        response = self.client.post(reverse("local-reset-confirm"), {
            "identifier": "local@example.com", "code": "654321", "password": "mat-khau-moi-du-dai"}, format="json")
        self.assertEqual(response.status_code, 200)
        local.refresh_from_db()
        self.assertTrue(local.check_password("mat-khau-moi-du-dai"))


class EmailOtpSettingsTest(TestCase):
    def setUp(self):
        roles.ensure_groups()
        self.admin = User.objects.create_user("admin", email="admin@example.com", password="mat-khau-dai-1")
        self.admin.groups.add(Group.objects.get(name=roles.ADMIN))
        self.normal_user = User.objects.create_user("normal_user", email="normal@example.com", password="mat-khau-dai-2")
        self.config = EmailOtpSettings.current()
        self.config.set_api_key("re_test_key")
        self.config.from_email = "radar@example.com"
        self.config.enabled = True
        self.config.save()

    def test_admin_luu_config_khong_tra_api_key(self):
        self.client.force_login(self.admin)
        response = self.client.patch(reverse("email-otp-settings"), {
            "enabled": True, "api_key": "re_secret_value", "from_email": "radar@example.com",
            "from_name": "Radar", "code_ttl_seconds": 600,
            "resend_cooldown_seconds": 60, "max_attempts": 5,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["api_key_configured"])
        self.assertNotIn("re_secret_value", response.content.decode())
        self.assertNotIn("re_secret_value", EmailOtpSettings.current().resend_api_key_encrypted)

    def test_admin_khong_the_keo_dai_otp_qua_10_phut(self):
        self.client.force_login(self.admin)
        response = self.client.patch(reverse("email-otp-settings"), {"code_ttl_seconds": 601},
                                     content_type="application/json")
        self.assertEqual(response.status_code, 400)

    @override_settings(ALLOWED_HOSTS=["dev-radar.tunghr.io.vn", "localhost", "127.0.0.1", "testserver"])
    def test_admin_luon_nhan_url_webhook_https_sau_reverse_proxy(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("email-otp-settings"), HTTP_HOST="dev-radar.tunghr.io.vn")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["webhook_url"],
                         "https://dev-radar.tunghr.io.vn/api/v1/auth/resend/webhook/")

    def test_admin_chap_nhan_nhieu_reply_to(self):
        self.client.force_login(self.admin)
        response = self.client.patch(reverse("email-otp-settings"), {
            "reply_to": "support@example.com; it@example.com"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EmailOtpSettings.current().reply_to,
                         "support@example.com,it@example.com")

    def test_admin_luu_allowed_domains_dang_mang_khong_bi_stringify(self):
        self.client.force_login(self.admin)
        response = self.client.patch(reverse("email-otp-settings"), {
            "allowed_domains": ["tntalent.vn", "msb.com.vn"]}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        config = EmailOtpSettings.current()
        self.assertEqual(config.tntalent_domains, "tntalent.vn")
        self.assertEqual(config.msb_domains, "msb.com.vn")

    def test_migration_ghi_lai_domain_bi_stringify_thanh_dang_phang(self):
        from importlib import import_module

        from django.apps import apps as django_apps

        mod = import_module("accounts.migrations.0014_normalize_email_otp_domains")
        config = EmailOtpSettings.current()
        # Chuỗi bẩn nhiều lớp kiểu str(list) lồng nhau như trên bản Oracle.
        config.tntalent_domains = "[\"['[\\\"tntalent.vn\\\"]']\"]"
        config.msb_domains = "['[\\'msb.com.vn\\']']"
        config.save(update_fields=["tntalent_domains", "msb_domains"])
        mod.normalize_domains(django_apps, None)
        config.refresh_from_db()
        self.assertEqual(config.tntalent_domains, "tntalent.vn")
        self.assertEqual(config.msb_domains, "msb.com.vn")

    def test_webhook_chi_nhan_payload_co_chu_ky_hop_le(self):
        config = EmailOtpSettings.current()
        secret_bytes = b"webhook-test-secret-32-bytes-long!"
        secret = "whsec_" + base64.b64encode(secret_bytes).decode()
        config.set_webhook_secret(secret)
        config.save(update_fields=["webhook_secret_encrypted"])
        payload = json.dumps({"type": "email.delivered", "created_at": "2026-08-31T00:00:00Z",
                              "data": {"email_id": "mail-1"}}, separators=(",", ":")).encode()
        msg_id, timestamp = "msg_test", str(int(time.time()))
        signature = base64.b64encode(hmac.new(
            secret_bytes, f"{msg_id}.{timestamp}.".encode() + payload, hashlib.sha256).digest()).decode()
        response = self.client.post(reverse("resend-webhook"), data=payload,
                                    content_type="application/json", **{
                                        "HTTP_SVIX_ID": msg_id, "HTTP_SVIX_TIMESTAMP": timestamp,
                                        "HTTP_SVIX_SIGNATURE": f"v1,{signature}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ResendWebhookEvent.objects.get().event_type, "email.delivered")

    @mock.patch("accounts.email_otp._send_resend")
    def test_admin_gui_test_otp_thanh_cong(self, mock_send):
        mock_send.return_value = {"id": "re_test_email_123"}
        self.client.force_login(self.admin)
        response = self.client.post(reverse("email-otp-test-send"),
                                    {"recipient": "test-user@msb.com.vn"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["recipient"], "test-user@msb.com.vn")
        self.assertEqual(data["resend_id"], "re_test_email_123")
        self.assertTrue(mock_send.called)
        self.assertTrue(AuthenticationEvent.objects.filter(result="email_otp_test_sent").exists())

    def test_user_thuong_khong_duoc_gui_test_otp(self):
        self.client.force_login(self.normal_user)
        response = self.client.post(reverse("email-otp-test-send"),
                                    {"recipient": "test-user@msb.com.vn"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_admin_gui_test_otp_email_khong_hop_le_bao_loi(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("email-otp-test-send"),
                                    {"recipient": "invalid-email-format"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)


