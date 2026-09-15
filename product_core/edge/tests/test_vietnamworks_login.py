import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from selenium.common.exceptions import TimeoutException

from app.providers.vietnamworks import VietnamWorksProvider


class VietnamWorksLoginTests(unittest.TestCase):
    @patch("app.providers.vietnamworks.safe_get")
    @patch("selenium.webdriver.support.ui.WebDriverWait")
    def test_disabled_submit_falls_back_to_manual_login_wait(self, wait_cls, _safe_get):
        provider = VietnamWorksProvider(SimpleNamespace(
            vietnamworks_email="a@example.test", vietnamworks_password="secret"),
            log=lambda *_: None)
        provider.driver = MagicMock()
        email = MagicMock()
        password = MagicMock()
        provider.driver.find_element.return_value = password
        provider.driver.find_elements.return_value = []
        waiter = wait_cls.return_value
        waiter.until.side_effect = [email, TimeoutException("disabled")]
        provider._wait_login = MagicMock()

        provider._login()

        provider._wait_login.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
