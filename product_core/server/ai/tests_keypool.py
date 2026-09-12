# -*- coding: utf-8 -*-
"""Kiểm thử xoay vòng nhiều khoá cho cùng một nhà cung cấp.

Bối cảnh đo được: khoá Gemini miễn phí bị HTTP 429 sau ~15 lượt gọi/phút — đúng
nhịp một buổi demo. Hạn mức tính THEO TỪNG KHOÁ nên ba khoá là hạn mức gấp ba.
"""
from django.test import TestCase

from .keypool import KeyPool, RATE_LIMIT_COOLDOWN, split_keys
from .models import ProviderConfig
from .providers import LLMAuthError, LLMUnavailable, OpenAICompatibleProvider


class SplitKeysTest(TestCase):
    def test_nhan_nhieu_dau_phan_cach(self):
        """Người dùng dán khoá từ nhiều chỗ nên định dạng rất tuỳ hứng."""
        for text in ("a,b,c", "a;b;c", "a\nb\nc", "a, b\nc", "a\r\nb\r\nc"):
            self.assertEqual(split_keys(text), ["a", "b", "c"], text)

    def test_bo_khoang_trang_va_dong_rong(self):
        self.assertEqual(split_keys("  a  ,\n\n , b "), ["a", "b"])

    def test_mot_khoa_van_ra_danh_sach(self):
        self.assertEqual(split_keys("sk-abc"), ["sk-abc"])

    def test_rong(self):
        self.assertEqual(split_keys(""), [])
        self.assertEqual(split_keys(None), [])


class KeyPoolTest(TestCase):
    def test_xoay_vong_deu_giua_cac_khoa(self):
        """Luôn lấy khoá đầu nghĩa là khoá đầu lúc nào cũng sắp hết hạn mức."""
        pool = KeyPool(["k1", "k2", "k3"])
        lay = [pool.acquire().key for _ in range(6)]
        self.assertEqual(len(set(lay)), 3)
        self.assertEqual(lay[:3], lay[3:], "phải xoay đúng chu kỳ")

    def test_bo_khoa_trung(self):
        self.assertEqual(len(KeyPool(["k1", "k1", "k2"])), 2)

    def test_het_han_muc_thi_cho_nghi_KHONG_tat(self):
        """Hạn mức sẽ hồi; tắt khoá là vứt đi một khoá còn tốt."""
        pool = KeyPool(["k1", "k2"])
        state = pool.acquire()
        pool.report_rate_limited(state)

        self.assertFalse(state.disabled)
        self.assertFalse(state.available)
        self.assertGreater(state.cooling_seconds, RATE_LIMIT_COOLDOWN - 5)
        self.assertEqual(pool.usable, 1)

    def test_khoa_sai_thi_TAT_HAN(self):
        """Thử lại khoá sai chỉ tổ phí và làm rác nhật ký."""
        pool = KeyPool(["k1", "k2"])
        state = pool.acquire()
        pool.report_invalid(state)
        self.assertTrue(state.disabled)
        self.assertEqual(pool.usable, 1)

    def test_khoa_dang_nghi_khong_duoc_lay(self):
        pool = KeyPool(["k1", "k2"])
        pool.report_rate_limited(pool.states[0])
        for _ in range(4):
            self.assertEqual(pool.acquire().key, "k2")

    def test_moi_khoa_dang_nghi_thi_VAN_tra_khoa_het_nghi_som_nhat(self):
        """Thời gian nghỉ chỉ là phỏng đoán — bỏ cuộc khi còn khoá dùng được là tệ hơn.

        Đây cũng là thứ giúp vòng thử lại của router có tác dụng với nhà cung cấp
        chỉ có một khoá: nghỉ 60 giây mà router thử lại sau 3 giây, không có lối
        này thì retry không bao giờ thành công.
        """
        pool = KeyPool(["k1", "k2"])
        for state in pool.states:
            pool.report_rate_limited(state)
        pool.states[0].cooldown_until -= 30      # k1 hết nghỉ sớm hơn

        state = pool.acquire()
        self.assertIsNotNone(state)
        self.assertEqual(state.key, "k1")

    def test_moi_khoa_deu_TAT_thi_tra_None(self):
        """Khoá đã tắt thì đúng là hỏng, không đụng tới."""
        pool = KeyPool(["k1", "k2"])
        for state in pool.states:
            pool.report_invalid(state)
        self.assertIsNone(pool.acquire())

    def test_pool_rong(self):
        pool = KeyPool([])
        self.assertEqual(len(pool), 0)
        self.assertIsNone(pool.acquire())

    def test_status_khong_lo_khoa(self):
        pool = KeyPool(["sk-bi-mat-tuyet-doi-12345"])
        text = str(pool.status())
        self.assertNotIn("tuyet-doi", text)
        self.assertNotIn("12345", text)


class ProviderRotationTest(TestCase):
    """Xoay khoá phải xảy ra TRƯỚC khi chuyển nhà cung cấp."""

    def _provider(self, keys, responder):
        calls = []

        def transport(url, headers, body, timeout):
            key = headers["Authorization"].replace("Bearer ", "")
            calls.append(key)
            return responder(key)

        provider = OpenAICompatibleProvider(
            "test", "https://api.test/v1", keys, "m", transport=transport)
        return provider, calls

    OK = (200, {"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    def test_nhan_chuoi_nhieu_khoa(self):
        provider, _ = self._provider("k1,k2,k3", lambda k: self.OK)
        self.assertEqual(len(provider.keys), 3)

    def test_khoa_dau_het_han_muc_thi_dung_khoa_sau(self):
        def responder(key):
            return (429, {"error": {"message": "quá nhanh"}}) if key == "k1" else self.OK

        provider, calls = self._provider(["k1", "k2"], responder)
        result = provider.complete([{"role": "user", "content": "x"}])

        self.assertEqual(result.text, "ok")
        self.assertEqual(calls, ["k1", "k2"], "phải tự chuyển sang khoá thứ hai")
        self.assertEqual(provider.keys.usable, 1, "khoá hết hạn mức đang nghỉ")

    def test_khoa_sai_thi_bo_qua_va_dung_khoa_sau(self):
        def responder(key):
            return (401, {"error": {"message": "sai khoá"}}) if key == "k1" else self.OK

        provider, calls = self._provider(["k1", "k2"], responder)
        self.assertEqual(provider.complete([{"role": "user", "content": "x"}]).text, "ok")
        self.assertEqual(calls, ["k1", "k2"])
        self.assertTrue(provider.keys.states[0].disabled)

    def test_MOI_khoa_deu_het_han_muc_thi_bao_loi_tam_thoi(self):
        """Tạm thời, để router còn biết mà chuyển nhà cung cấp hoặc thử lại."""
        provider, calls = self._provider(
            ["k1", "k2"], lambda k: (429, {"error": {"message": "quá nhanh"}}))
        with self.assertRaises(LLMUnavailable):
            provider.complete([{"role": "user", "content": "x"}])
        self.assertEqual(len(calls), 2, "phải thử hết mọi khoá trước khi bỏ cuộc")

    def test_khoa_dang_nghi_van_duoc_thu_lai_o_luot_sau(self):
        """Nghỉ 60s mà router thử lại sau 3s — không có lối này thì retry vô dụng."""
        lan = {"n": 0}

        def responder(key):
            lan["n"] += 1
            if lan["n"] == 1:
                return (429, {"error": {"message": "quá nhanh"}})
            return self.OK

        provider, _ = self._provider(["chi-mot-khoa"], responder)
        with self.assertRaises(LLMUnavailable):
            provider.complete([{"role": "user", "content": "x"}])
        # Lượt sau vẫn dùng lại được đúng khoá đó dù nó đang trong thời gian nghỉ.
        self.assertEqual(provider.complete([{"role": "user", "content": "x"}]).text, "ok")

    def test_MOI_khoa_deu_sai_thi_bao_loi_xac_thuc(self):
        provider, _ = self._provider(
            ["k1", "k2"], lambda k: (401, {"error": {"message": "sai"}}))
        with self.assertRaises(LLMAuthError):
            provider.complete([{"role": "user", "content": "x"}])

    def test_loi_5xx_KHONG_phat_khoa(self):
        """5xx là lỗi của nhà cung cấp, không phải của khoá. Đổi khoá vô ích."""
        provider, calls = self._provider(["k1", "k2"], lambda k: (503, {}))
        with self.assertRaises(LLMUnavailable):
            provider.complete([{"role": "user", "content": "x"}])
        self.assertEqual(len(calls), 1, "không thử khoá khác")
        self.assertEqual(provider.keys.usable, 2, "không khoá nào bị phạt")

    def test_mot_khoa_van_chay_nhu_cu(self):
        provider, calls = self._provider("chi-mot-khoa", lambda k: self.OK)
        self.assertEqual(provider.complete([{"role": "user", "content": "x"}]).text, "ok")
        self.assertEqual(calls, ["chi-mot-khoa"])


class ConfigMultiKeyTest(TestCase):
    def setUp(self):
        self.config = ProviderConfig.objects.create(provider=ProviderConfig.GEMINI)

    def test_luu_va_doc_lai_nhieu_khoa(self):
        self.config.set_api_key("AIza-mot, AIza-hai\nAIza-ba")
        self.config.save()
        row = ProviderConfig.objects.get(pk=self.config.pk)
        self.assertEqual(row.get_api_keys(), ["AIza-mot", "AIza-hai", "AIza-ba"])
        self.assertEqual(row.key_count, 3)

    def test_khoa_khong_luu_dang_ro(self):
        self.config.set_api_key("AIza-bi-mat-1,AIza-bi-mat-2")
        self.assertNotIn("bi-mat", self.config.api_key_encrypted)

    def test_hint_hien_nhieu_khoa_nhung_khong_lo(self):
        self.config.set_api_key("AIzaAAAAAAAAAA,AIzaBBBBBBBBBB")
        self.assertIn(",", self.config.api_key_hint)
        self.assertNotIn("AAAAAAAAAA", self.config.api_key_hint)

    def test_nhieu_hon_ba_khoa_thi_rut_gon_hint(self):
        self.config.set_api_key(",".join(f"AIzaKey{i}xxxxx" for i in range(5)))
        self.assertIn("+2", self.config.api_key_hint)

    def test_get_api_key_van_tra_khoa_dau(self):
        self.config.set_api_key("mot,hai")
        self.assertEqual(self.config.get_api_key(), "mot")

    def test_xoa_het_khoa(self):
        self.config.set_api_key("a,b")
        self.config.set_api_key("")
        self.assertEqual(self.config.get_api_keys(), [])
        self.assertFalse(self.config.has_api_key)

    def test_router_dung_ca_nhom_khoa(self):
        from .router import Router, reset_router
        reset_router()
        self.addCleanup(reset_router)
        self.config.enabled = True
        self.config.model = "m"
        self.config.set_api_key("k1,k2,k3")
        self.config.save()
        provider = Router(env={}).get_provider("gemini")
        self.assertEqual(len(provider.keys), 3)
