import unittest
from types import SimpleNamespace

from app.providers.joboko import JobokoProvider


HREF1 = ("https://em-vn.joboko.com/xem-ho-so-4393db9eb0a64cdd-4306526"
         "?src=1&jid=6654362&ref=ungtuyenJob&utm_medium=listcv")
HREF2 = "/xem-ho-so-f7c663cc62a2adc1-4300075?src=1&jid=6470018"


class JobokoProviderTests(unittest.TestCase):
    def setUp(self):
        cfg = SimpleNamespace(joboko_email="employer@example.test",
                              joboko_password="secret")
        self.provider = JobokoProvider(cfg, log=lambda *_: None)

    def test_parse_items_reads_row_and_dedupes(self):
        html = f"""
        <div class="item">
          <div class="item-content"><div class="item-title">
            <a class="fz-15 text-view-cv" href="{HREF1}">NGUYỄN THỊ KHEN</a>
          </div>
          <div class="item-info">Online gần đây khennguyen88@gmail.com 0973264860 Đã mở quyền</div>
          </div>
        </div>
        <div class="item"><div class="item-title">
          <a class="text-view-cv" href="{HREF2}">Nguyễn Hoàng Sơn</a>
          <a class="text-view-cv" href="{HREF2}">Nguyễn Hoàng Sơn</a>
        </div></div>
        """
        items = self.provider._parse_items(html)
        self.assertEqual([it["cv_id"] for it in items], ["4306526", "4300075"])
        first = items[0]
        self.assertEqual(first["fullname"], "NGUYỄN THỊ KHEN")
        self.assertEqual(first["source"], "joboko")
        self.assertEqual(first["email"], "khennguyen88@gmail.com")
        self.assertEqual(first["phone"], "0973264860")
        self.assertEqual(first["apply_source"], "Joboko")
        self.assertEqual(first["cv_url"], HREF1)
        self.assertEqual(items[1]["cv_url"], "https://em-vn.joboko.com" + HREF2)

    def test_parse_items_reads_campaign_id_from_jid(self):
        """`jid` trong href danh sách = mã tin đã ứng tuyển (khớp `IdJob` trong
        `jbkCVInfo` ở trang chi tiết). Nhóm ứng viên theo tin ngay từ danh sách,
        không cần mở chi tiết."""
        html = f'<div class="item"><a class="text-view-cv" href="{HREF1}">A</a></div>'
        items = self.provider._parse_items(html)
        self.assertEqual(items[0]["campaign_id"], "6654362")
        self.assertEqual(items[0]["position"], "")

    def test_parse_detail_fields_reads_position_and_job_id_from_jbkcvinfo(self):
        """Joboko nhét dữ liệu ứng tuyển vào biến JS `jbkCVInfo` (JSON). Vị trí
        ứng tuyển nằm trong `TxtNote` sau cụm "ứng tuyển việc làm"."""
        html = (
            "<script> var jbkCVInfo = '"
            '{"Id":2812624,"IdJob":"6654362","IdCamp":"","TxtNote":'
            '"Ứng viên Đoàn Thu Phương Anh ứng tuyển việc làm '
            '[RVI] Chuyên Viên Phát Triển Khách Hàng Cá Nhân - Hà Nội - RB - MSB - 1O323"}'
            "' </script>")
        fields = JobokoProvider._parse_detail_fields(html)
        self.assertEqual(fields["campaign_id"], "6654362")
        self.assertEqual(
            fields["position"],
            "[RVI] Chuyên Viên Phát Triển Khách Hàng Cá Nhân - Hà Nội - RB - MSB - 1O323")

    def test_parse_detail_fields_empty_without_jbkcvinfo(self):
        self.assertEqual(JobokoProvider._parse_detail_fields("<html>no script</html>"), {})

    def test_apply_detail_fields_only_fills_blanks_and_marks_loaded(self):
        html = ("<script>var jbkCVInfo = '"
                '{"IdJob":"999","TxtNote":"x ứng tuyển việc làm Kế toán trưởng"}'
                "'</script>")
        item = {"position": "Đã có sẵn", "campaign_id": ""}
        self.provider._apply_detail_fields(item, html)
        self.assertEqual(item["position"], "Đã có sẵn")       # không đè
        self.assertEqual(item["campaign_id"], "999")          # điền chỗ trống
        self.assertEqual(item["detail_loaded"], 1)

    def test_supports_detail_enrichment(self):
        self.assertTrue(self.provider.supports_detail_enrichment)

    def test_parse_items_ignores_login_page(self):
        html = '<form><input type="password" name="pass"><button>Đăng nhập</button></form>'
        self.assertEqual(self.provider._parse_items(html), [])

    def test_parse_total_from_data_row(self):
        html = '<span class="fw-bold data-row">89</span> hồ sơ'
        self.assertEqual(self.provider._parse_total(html, 10), 89)

    def test_parse_total_from_text_fallback(self):
        html = '<p>Tìm thấy <b>1.234</b> hồ sơ CV Ứng tuyển</p>'
        self.assertEqual(self.provider._parse_total(html, 10), 1234)

    def test_detect_file(self):
        self.assertIsNone(self.provider._detect_file(b"<html>login</html>"))
        self.assertEqual(self.provider._detect_file(b"x" * 20 + b"%PDF-1.7"), ".pdf")
        self.assertEqual(self.provider._detect_file(b"\xd0\xcf\x11\xe0rest"), ".doc")
        self.assertEqual(self.provider._detect_file(b"PK\x03\x04rest"), ".docx")

    def test_concurrency_is_serial(self):
        self.assertEqual(self.provider.concurrency_limit(), 1)

    def test_headless_preference(self):
        # mặc định: chạy ẩn
        self.assertTrue(self.provider._prefer_headless())
        self.assertFalse(self.provider._force_headless())
        # người dùng tắt "chạy ẩn" cho Joboko
        p2 = JobokoProvider(SimpleNamespace(joboko_email="a", joboko_password="b",
                                            joboko_headless=False), log=lambda *_: None)
        self.assertFalse(p2._prefer_headless())
        # ép ẩn toàn cục -> luôn ẩn kể cả khi joboko_headless=False
        p3 = JobokoProvider(SimpleNamespace(joboko_email="a", joboko_password="b",
                                            joboko_headless=False, headless=True),
                            log=lambda *_: None)
        self.assertTrue(p3._prefer_headless())
        self.assertTrue(p3._force_headless())

    def test_iter_pages_raises_on_empty_page(self):
        self.provider._last_page = 2
        self.provider._first_page_items = [{"cv_id": "1"}]
        self.provider._driver_lock  # noqa
        self.provider._url = lambda: "https://em-vn.joboko.com/cv"
        self.provider._on_login_page = lambda: False
        self.provider._wait_list = lambda *a, **k: None
        self.provider._goto_page = lambda page: True
        self.provider._html = lambda: "<html><body>no rows</body></html>"
        it = self.provider.iter_pages(1, 2)
        self.assertEqual(next(it)[0], 1)
        with self.assertRaises(RuntimeError):
            next(it)


if __name__ == "__main__":
    unittest.main()
