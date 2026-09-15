# -*- coding: utf-8 -*-
"""Watchdog cho lượt tải theo lịch bị treo (`Api._force_recover_stuck_download`).

Đồng bộ Hub đã có `STALE_RUN_SECONDS` tự huỷ lượt treo quá 10 phút; luồng tải
CV theo lịch trước đây không có gì tương đương - một Chrome/chromedriver bị
deadlock ở tầng driver có thể chặn TOÀN BỘ lịch còn lại (mọi nhà cung cấp, mọi
tài khoản) vô thời hạn. `_force_recover_stuck_download` là lưới an toàn cuối:
yêu cầu dừng hợp tác rồi ép đóng Chrome của mọi tài khoản thuộc nguồn đó, để
lệnh Selenium đang treo gặp lỗi kết nối và luồng tải tự thoát.
"""
import unittest
from unittest.mock import patch

from app.web_api import Api


class FakeConfig:
    def __init__(self, accounts):
        self._accounts = accounts

    def accounts_for_source(self, source, enabled_only=True):
        return list(self._accounts)

    def for_account(self, account):
        return account


def _api_with_accounts(accounts):
    api = Api.__new__(Api)
    api._cfg = FakeConfig(accounts)
    api.log = lambda *a, **k: None
    api.stop_download = lambda: {"ok": True}
    api._provider_browser_target = lambda source, cfg: (lambda: f"/profile/{cfg.get('id')}", "https://x")
    return api


class ForceRecoverStuckDownloadTests(unittest.TestCase):
    def test_returns_true_once_download_thread_actually_stops(self):
        api = _api_with_accounts([{"id": "acc1"}, {"id": "acc2"}])
        calls = {"n": 0}

        def fake_is_downloading():
            calls["n"] += 1
            return calls["n"] < 2          # còn "treo" ở lần kiểm tra đầu, hết ở lần sau

        api.is_downloading = fake_is_downloading
        with patch("app.web_api.close_profile_browser") as closer, \
             patch("app.web_api.time.sleep", lambda _s: None):
            ok = api._force_recover_stuck_download("jobsgo")
        self.assertTrue(ok)
        # Phải đóng Chrome của TẤT CẢ tài khoản thuộc nguồn này, không chỉ một.
        self.assertEqual(closer.call_count, 2)

    def test_returns_false_when_thread_never_dies_within_grace_period(self):
        api = _api_with_accounts([{"id": "acc1"}])
        api.is_downloading = lambda: True   # không bao giờ hết treo
        with patch("app.web_api.close_profile_browser"), \
             patch("app.web_api.SCHEDULED_JOB_KILL_GRACE_SECONDS", 0), \
             patch("app.web_api.time.sleep", lambda _s: None):
            ok = api._force_recover_stuck_download("jobsgo")
        self.assertFalse(ok)

    def test_still_tries_to_close_profiles_even_if_stop_download_raises(self):
        """`stop_download()` là dừng hợp tác (best-effort) - nếu chính nó lỗi
        (vd engine đã ở trạng thái lạ), vẫn phải tiếp tục ép đóng Chrome chứ
        không được bỏ cuộc giữa chừng."""
        api = _api_with_accounts([{"id": "acc1"}])

        def boom():
            raise RuntimeError("engine đang ở trạng thái không xác định")

        api.stop_download = boom
        api.is_downloading = lambda: False
        with patch("app.web_api.close_profile_browser") as closer, \
             patch("app.web_api.time.sleep", lambda _s: None):
            ok = api._force_recover_stuck_download("jobsgo")
        self.assertTrue(ok)
        closer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
