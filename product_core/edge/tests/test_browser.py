import time
from unittest.mock import patch

import pytest

from app.browser import CHROME_START_TIMEOUT, ChromeStartError, _start_with_watchdog


def test_chrome_start_timeout_allows_slow_first_run():
    assert CHROME_START_TIMEOUT >= 120


def test_watchdog_reports_actual_timeout_and_cleans_owned_processes():
    def never_finishes():
        time.sleep(0.2)

    with patch("app.browser._cleanup_owned_browser_processes") as cleanup:
        with pytest.raises(ChromeStartError) as exc_info:
            _start_with_watchdog(never_finishes, "safe-test-profile", timeout=0.05)

    cleanup.assert_called_once_with("safe-test-profile")
    assert "1 giây" in str(exc_info.value)
    assert "kiểm tra kết nối mạng" in str(exc_info.value)
