import unittest
from types import SimpleNamespace

from app.providers.itviec import ITViecProvider


UUID1 = "58239aa7-e5db-4585-9650-8be13bad5411"
UUID2 = "11111111-2222-3333-4444-555555555555"


class ITViecProviderTests(unittest.TestCase):
    def setUp(self):
        cfg = SimpleNamespace(itviec_email="employer@example.test", itviec_password="secret")
        self.provider = ITViecProvider(cfg, log=lambda *_: None)

    def test_parse_items_normalizes_date_and_ignores_download_link(self):
        html = f"""
        <table><tr><td><a href="/customer/job-applications/{UUID1}">Nguyễn Văn A</a></td>
        <td>a@example.test 0901 234 567</td>
        <td><a href="/customer/jobs/backend-engineer">Backend Engineer</a></td>
        <td>11-08-2026 17:45</td>
        <td><a href="/customer/job-applications/{UUID1}/downloads">Download</a></td></tr></table>
        """
        items = self.provider._parse_items(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["cv_id"], UUID1)
        self.assertEqual(items[0]["phone"], "0901234567")
        self.assertEqual(items[0]["applied_at"], "11/08/2026 17:45")
        self.assertEqual(items[0]["applied_ts"], "2026-08-11 17:45:00")
        self.assertEqual(items[0]["campaign_id"], "backend-engineer")

    def test_extract_phone_does_not_swallow_digit_of_next_word(self):
        """Hồi quy: dòng ứng viên nối bằng dấu cách, một nhãn bắt đầu bằng chữ
        số đứng ngay sau SĐT (vd "N years experience") từng bị nuốt vào cuối
        số điện thoại. Xem memory edge-dom-text-regex-swallow-bug."""
        f = self.provider._extract_phone
        self.assertEqual(f("a@x.test 0901234567 5 years experience"), "0901234567")
        self.assertEqual(f("a@x.test 0901234567 2026 Download"), "0901234567")
        self.assertEqual(f("a@x.test 0901234567 Backend Engineer"), "0901234567")
        self.assertEqual(f("a@x.test 0901 234 567 Backend Engineer"), "0901234567")
        self.assertEqual(f("a@x.test +84901234567 Backend Engineer"), "0901234567")
        self.assertEqual(f("a@x.test không có số điện thoại"), "")

    def test_first_page_uses_pagination_and_summary_not_year(self):
        html = f"""
        <div>Showing 1-100 of 125 applications</div>
        <div class="number">2026</div>
        <a href="?page=2&per=100">2</a>
        <a href="/customer/job-applications/{UUID1}">A</a>
        """
        self.provider._parse_first_page(html)
        self.assertEqual(self.provider.total_count(), 125)
        self.assertEqual(self.provider.last_page, 2)

    def test_file_detection_rejects_html_and_accepts_supported_files(self):
        self.assertIsNone(self.provider._detect_file(b"<html>login</html>", "text/html"))
        self.assertEqual(self.provider._detect_file(b"x" * 20 + b"%PDF-1.7"), ".pdf")
        self.assertEqual(self.provider._detect_file(b"PK\x03\x04rest", filename="cv.docx"), ".docx")

    def test_iter_pages_raises_on_empty_middle_page(self):
        self.provider._last_page = 2
        self.provider._first_page_items = [{"cv_id": UUID1}]
        response = SimpleNamespace(status_code=200, text="<html></html>")
        self.provider._request = lambda *args, **kwargs: response
        iterator = self.provider.iter_pages(1, 2)
        self.assertEqual(next(iterator)[0], 1)
        with self.assertRaises(RuntimeError):
            next(iterator)

    def test_visible_element_skips_disabled_language_submit(self):
        class Element:
            def __init__(self, enabled):
                self.enabled = enabled

            def is_displayed(self):
                return True

            def is_enabled(self):
                return self.enabled

        disabled_language = Element(False)
        sign_in = Element(True)
        elements = {"generic-submit": disabled_language, "sign-in": sign_in}
        self.provider.driver = SimpleNamespace(
            find_element=lambda _by, selector: elements[selector])
        found = self.provider._visible_element([
            ("css selector", "generic-submit"),
            ("css selector", "sign-in"),
        ])
        self.assertIs(found, sign_in)


if __name__ == "__main__":
    unittest.main()
