import threading
import unittest
from types import SimpleNamespace

from app.providers.topcv import TopCVProvider


class Response:
    def __init__(self, retry_after=""):
        self.headers = {"Retry-After": retry_after} if retry_after else {}


class TopCVResilienceTests(unittest.TestCase):
    def test_retry_after_is_honoured_and_capped(self):
        self.assertEqual(TopCVProvider._retry_delay(Response("7"), 0), 7)
        self.assertEqual(TopCVProvider._retry_delay(Response("999"), 0), 60)

    def test_invalid_retry_after_uses_bounded_backoff(self):
        delay = TopCVProvider._retry_delay(Response("invalid"), 2)
        self.assertGreaterEqual(delay, 4.25)
        self.assertLessEqual(delay, 5.25)


class TopCVRelocationScrapeTests(unittest.TestCase):
    """Sidebar "Thông tin bổ sung từ ứng viên" trên trang chi tiết CV có
    "Sẵn sàng di chuyển (Địa điểm)" = nơi làm việc mong muốn. Cấu trúc thật
    (trang đã lưu): <div class="relocation-label"> <div class="info">
    <span class="text">Sẵn sàng di chuyển</span> <span class="more">
    (Hồ Chí Minh)</span></div></div>."""

    class _El:
        def __init__(self, text_content):
            self._t = text_content

        def get_attribute(self, name):
            return self._t if name == "textContent" else ""

    def _provider(self, selector_map, current_url="https://tuyendung.topcv.vn/app/cvs-management/cvs/1"):
        provider = TopCVProvider.__new__(TopCVProvider)
        provider._driver_lock = threading.Lock()
        provider.log = lambda *a, **k: None
        provider.driver = SimpleNamespace(
            current_url=current_url,
            find_elements=lambda _by, sel: selector_map.get(sel, []))
        return provider

    def test_extracts_location_from_relocation_label(self):
        import app.providers.topcv as mod
        orig_get, orig_sleep = mod.safe_get, mod.time.sleep
        mod.safe_get = lambda *a, **k: None
        mod.time.sleep = lambda _s: None
        try:
            provider = self._provider(
                {".relocation-label": [self._El("Sẵn sàng di chuyển (Hồ Chí Minh)")]})
            item = {"cv_url": "https://tuyendung.topcv.vn/app/cvs-management/cvs/123"}
            provider._scrape_relocation(item)
        finally:
            mod.safe_get, mod.time.sleep = orig_get, orig_sleep
        self.assertEqual(item["desired_location"], "Hồ Chí Minh")
        self.assertEqual(item["detail_loaded"], 1)

    def test_stops_after_grace_when_no_relocation_label(self):
        """Ứng viên không khai -> `.relocation-label` vắng; trang đã dựng
        (`.campaign-box`) -> chờ thêm grace rồi thôi, không treo hết 25 giây."""
        import app.providers.topcv as mod
        orig_get, orig_sleep = mod.safe_get, mod.time.sleep
        mod.safe_get = lambda *a, **k: None
        mod.time.sleep = lambda _s: None
        try:
            provider = self._provider({".campaign-box, .cv-preview, .modal-cv, iframe": [SimpleNamespace()]})
            item = {"cv_url": "https://tuyendung.topcv.vn/app/cvs-management/cvs/123"}
            provider._scrape_relocation(item)
        finally:
            mod.safe_get, mod.time.sleep = orig_get, orig_sleep
        self.assertNotIn("desired_location", item)
        self.assertEqual(item["detail_loaded"], 1)

    def test_skips_when_redirected_to_login(self):
        import app.providers.topcv as mod
        orig_get = mod.safe_get
        mod.safe_get = lambda *a, **k: None
        try:
            provider = self._provider({}, current_url="https://tuyendung.topcv.vn/app/login")
            item = {"cv_url": "https://tuyendung.topcv.vn/app/cvs-management/cvs/1"}
            provider._scrape_relocation(item)
        finally:
            mod.safe_get = orig_get
        self.assertNotIn("desired_location", item)
        self.assertEqual(item["detail_loaded"], 1)

    def test_silent_without_driver(self):
        provider = TopCVProvider.__new__(TopCVProvider)
        provider.driver = None
        provider.log = lambda *a, **k: None
        item = {"cv_url": "x"}
        provider._scrape_relocation(item)
        self.assertEqual(item["desired_location"] if "desired_location" in item else None, None)
        self.assertEqual(item["detail_loaded"], 1)


if __name__ == "__main__":
    unittest.main()
