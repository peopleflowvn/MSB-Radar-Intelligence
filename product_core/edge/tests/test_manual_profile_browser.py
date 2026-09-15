import os
import tempfile
import unittest
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.browser import close_profile_browser, open_profile_browser
from app.config import AppConfig
from app.web_api import Api


class ManualProfileBrowserTests(unittest.TestCase):
    def test_opens_regular_chrome_with_exact_profile_and_no_automation_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            chrome = os.path.join(tmp, "chrome.exe")
            with open(chrome, "wb") as handle:
                handle.write(b"")
            profile = os.path.join(tmp, "provider-profile")
            with patch("undetected_chromedriver.find_chrome_executable", return_value=chrome), \
                    patch("app.browser.subprocess.Popen") as popen:
                self.assertTrue(open_profile_browser(profile, "https://example.test/account"))

            args = popen.call_args.args[0]
            self.assertEqual(args[0], chrome)
            self.assertIn(f"--user-data-dir={os.path.abspath(profile)}", args)
            self.assertEqual(args[-1], "https://example.test/account")
            self.assertFalse(any("remote-debugging" in arg or "AutomationControlled" in arg
                                 for arg in args))

    def test_manual_browser_is_blocked_while_download_is_running(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(email="test@example.test")
        api._lock = threading.Lock()
        api._engine_thread = SimpleNamespace(is_alive=lambda: True)
        with patch("app.web_api.open_profile_browser") as opener:
            result = api.open_provider_browser("topcv")
        self.assertFalse(result["ok"])
        self.assertIn("Đang có tiến trình", result["error"])
        opener.assert_not_called()

    def test_start_download_requires_confirmation_when_profile_is_open(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(email="test@example.test")
        account_id = api._cfg.accounts_for_source("topcv")[0]["id"]
        with patch("app.web_api.profile_browser_processes", return_value=[1234]):
            result = api.start_download("topcv", "moi", {"account_ids": [account_id]})
        self.assertFalse(result["ok"])
        self.assertTrue(result["requires_profile_close"])

    def test_confirmed_close_targets_only_matching_profile_processes(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("app.browser._profile_chrome_processes",
                      side_effect=[[1234], [], [], []]), \
                patch("app.browser.subprocess.run") as runner:
            self.assertEqual(close_profile_browser(os.path.join(tmp, "account_profile")), 1)
        command = runner.call_args.args[0]
        self.assertEqual(command[:3], ["taskkill", "/PID", "1234"])

    def test_all_channels_start_worker_without_reading_database_on_click(self):
        class DeferredThread:
            def __init__(self, target, daemon=False):
                self.target = target
                self.daemon = daemon
                self.started = False

            def start(self):
                self.started = True

            def is_alive(self):
                return self.started

        fields = {
            "topcv": "email",
            "vietnamworks": "vietnamworks_email",
            "careerviet": "careerviet_email",
            "vieclam24h": "vieclam24h_email",
            "itviec": "itviec_email",
            "joboko": "joboko_email",
            "jobsgo": "jobsgo_email",
        }
        for provider_id, email_field in fields.items():
            with self.subTest(provider=provider_id):
                api = Api.__new__(Api)
                api._cfg = AppConfig(**{email_field: "test@example.test"})
                api._lock = threading.Lock()
                api._db_lock = threading.RLock()
                api._db_access_lock = threading.RLock()
                api._engine_thread = None
                api._parsing = SimpleNamespace(running=lambda: False)
                api._coordinator = SimpleNamespace(notify_download_starting=lambda: None)
                api._data_stats_cache = None
                api._checkpoint_cache = {}
                api._db_conn = None
                api._db_conn_path = None
                api._exclusive_db_owner = False
                api._db = MagicMock(side_effect=AssertionError(
                    "click path must not read SQLite"))
                api.log = MagicMock()
                account_id = api._cfg.accounts_for_source(provider_id)[0]["id"]

                with patch("app.web_api.profile_browser_processes", return_value=[]), \
                        patch("app.web_api.threading.Thread", DeferredThread):
                    result = api.start_download(
                        provider_id, "moi", {"account_ids": [account_id]})

                self.assertTrue(result["ok"])
                self.assertTrue(api._engine_thread.started)
                api._db.assert_not_called()

    def test_start_download_returns_while_ui_database_query_holds_handoff_lock(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(email="test@example.test")
        api._lock = threading.Lock()
        api._db_lock = threading.RLock()
        api._db_access_lock = threading.RLock()
        api._engine_thread = None
        api._parsing = SimpleNamespace(running=lambda: False)
        api._coordinator = SimpleNamespace(notify_download_starting=lambda: None)
        api._data_stats_cache = None
        api._checkpoint_cache = {}
        api._db_conn = None
        api._db_conn_path = None
        api._exclusive_db_owner = False
        api.log = MagicMock()
        account_id = api._cfg.accounts_for_source("topcv")[0]["id"]

        class DeferredThread:
            def __init__(self, target, daemon=False):
                self.target = target
                self.started = False

            def start(self):
                self.started = True

            def is_alive(self):
                return self.started

        lock_held = threading.Event()
        release_lock = threading.Event()

        def hold_database_query():
            with api._db_access_lock:
                lock_held.set()
                release_lock.wait(2)

        holder = threading.Thread(target=hold_database_query)
        holder.start()
        self.assertTrue(lock_held.wait(1))
        started_at = time.perf_counter()
        try:
            with patch("app.web_api.profile_browser_processes", return_value=[]), \
                    patch("app.web_api.threading.Thread", DeferredThread):
                result = api.start_download(
                    "topcv", "moi", {"account_ids": [account_id]})
        finally:
            release_lock.set()
            holder.join(timeout=1)

        self.assertTrue(result["ok"])
        self.assertTrue(api._engine_thread.started)
        self.assertLess(time.perf_counter() - started_at, 1.0)

    def test_resume_without_loaded_checkpoint_returns_instead_of_querying_database(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(email="test@example.test")
        api._db_access_lock = threading.RLock()
        api._checkpoint_cache = {}
        api._db = MagicMock(side_effect=AssertionError("resume click must not read SQLite"))
        account_id = api._cfg.accounts_for_source("topcv")[0]["id"]

        with patch("app.web_api.profile_browser_processes", return_value=[]):
            result = api.start_download(
                "topcv", "resume", {"account_ids": [account_id]})

        self.assertFalse(result["ok"])
        self.assertTrue(result["retryable"])
        api._db.assert_not_called()

    def test_manual_download_requires_and_uses_exact_operating_account(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(provider_accounts=[
            {"id": "first", "source": "topcv", "email": "first@example.test",
             "label": "First", "enabled": True},
            {"id": "second", "source": "topcv", "email": "second@example.test",
             "label": "Second", "enabled": True},
        ])
        self.assertIn("chọn một tài khoản", api.start_download("topcv", "moi", {})["error"])
        options = api.get_providers()
        self.assertEqual([(row["id"], row["account_id"]) for row in options],
                         [("topcv", "first"), ("topcv", "second")])


if __name__ == "__main__":
    unittest.main()
