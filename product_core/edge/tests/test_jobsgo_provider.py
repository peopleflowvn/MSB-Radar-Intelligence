import os
import shutil
import tempfile
import time
import unittest
from types import SimpleNamespace

from app.providers.jobsgo import JobsGoProvider


HREF1 = "/candidate/detail?cid=eDdDVlFsYW1icHpRbHFoOHZudVN1UT09&jid=bE51SC9QdU5UN25ON3RHK2dVazVSdz09"
HREF2 = "/candidate/detail?cid=RlB4UDBQUXRJSEl2OEIvSXRLcmdldz09&jid=bE51SC9QdU5UN25ON3RHK2dVazVSdz09"


class JobsGoProviderTests(unittest.TestCase):
    def setUp(self):
        cfg = SimpleNamespace(jobsgo_email="employer@example.test",
                              jobsgo_password="secret")
        self.provider = JobsGoProvider(cfg, log=lambda *_: None)

    def test_parse_items_reads_row_fields(self):
        html = f"""
        <a class="text-grey text-bold" href="/job/detail/25006841978">Chuyên Viên Pháp Chế</a>
        <div class="candidate-item" style="padding:10px">
          <a class="candidate-name-link" href="{HREF1}">Nguyễn Thị Khen</a>
          <span>1982 nguyenvanb88@gmail.com 0901234567</span>
          <a class="files-link" href="{HREF1}&scroll=cv">1 file</a>
        </div>
        """
        items = self.provider._parse_items(html)
        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first["source"], "jobsgo")
        self.assertEqual(first["fullname"], "Nguyễn Thị Khen")
        self.assertEqual(first["email"], "nguyenvanb88@gmail.com")
        self.assertEqual(first["phone"], "0901234567")
        self.assertEqual(first["position"], "Chuyên Viên Pháp Chế")
        self.assertEqual(first["campaign_id"], "25006841978")
        self.assertEqual(first["apply_source"], "JobsGO")
        self.assertTrue(first["_has_file"])
        self.assertIn("candidate/detail?cid=eDdDVlFsYW1icHpRbHFoOHZudVN1UT09", first["cv_url"])

    def test_parse_items_groups_candidates_under_job_link(self):
        """Trên trang thật, một link tin tuyển dụng đứng TRƯỚC cả cụm ứng viên đã
        ứng tuyển vào tin đó (không phải anh em cùng khối với từng dòng ứng viên).
        Phải gán đúng theo thứ tự tài liệu, không phải leo cha từng dòng."""
        html = f"""
        <a class="text-grey text-bold" href="/job/detail/111">Job Một</a>
        <div><a class="candidate-name-link" href="{HREF1}">Ứng viên A</a></div>
        <div><a class="candidate-name-link" href="{HREF2}">Ứng viên B</a></div>
        <a class="text-grey text-bold" href="/job/detail/222">Job Hai</a>
        <div><a class="candidate-name-link" href="/candidate/detail?cid=X&jid=Y">Ứng viên C</a></div>
        """
        items = self.provider._parse_items(html)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["position"], "Job Một")
        self.assertEqual(items[0]["campaign_id"], "111")
        self.assertEqual(items[1]["position"], "Job Một")
        self.assertEqual(items[2]["position"], "Job Hai")
        self.assertEqual(items[2]["campaign_id"], "222")

    def test_parse_items_campaign_id_falls_back_to_jid_without_job_link(self):
        """Link tiêu đề tin phía trên cụm ứng viên hay đổi cấu trúc (2026-09 đã
        thấy 0/43 hồ sơ lấy được `position` từ danh sách). Khi không có link
        tin, `campaign_id` vẫn phải lấy được từ `jid` trong href (luôn có)."""
        html = f'<div><a class="candidate-name-link" href="{HREF1}">Ứng viên A</a></div>'
        items = self.provider._parse_items(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["campaign_id"],
                         "bE51SC9QdU5UN25ON3RHK2dVazVSdz09")
        self.assertEqual(items[0]["position"], "")

    def test_parse_items_dedupes_same_href(self):
        html = f"""
        <div class="candidate-item">
          <a class="candidate-name-link" href="{HREF1}">Nguyễn Thị Khen</a>
          <a class="candidate-name-link" href="{HREF1}">Nguyễn Thị Khen</a>
        </div>
        """
        items = self.provider._parse_items(html)
        self.assertEqual(len(items), 1)

    def test_parse_items_without_files_link_has_no_file(self):
        html = f'<div class="candidate-item"><a class="candidate-name-link" href="{HREF2}">Sơn</a></div>'
        items = self.provider._parse_items(html)
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["_has_file"])

    def test_parse_items_ignores_login_page(self):
        html = '<form><input type="password" name="pass"><button>Đăng nhập</button></form>'
        self.assertEqual(self.provider._parse_items(html), [])

    def test_parse_total_takes_plausible_max(self):
        html = '<div>3091 Ứng viên</div><div>0 Ứng viên</div><div>2 Ứng viên</div>'
        self.assertEqual(self.provider._parse_total(html, 100), 3091)

    def test_extract_cdn_urls_decodes_l_param(self):
        html = ('<a class="btn-download-cv" href="/tool/download?n=A&amp;'
                'l=https%3A%2F%2Fmedia.jobsgo.vn%2Fcv.pdf&amp;t=xyz">Tải xuống</a>')
        self.assertEqual(self.provider._extract_cdn_urls(html),
                         ["https://media.jobsgo.vn/cv.pdf"])

    def test_extract_cdn_urls_missing_returns_empty_list(self):
        self.assertEqual(self.provider._extract_cdn_urls("<div>không có nút tải</div>"), [])

    def test_extract_cdn_urls_returns_all_in_priority_order_deduped(self):
        """Một hồ sơ có thể có NHIỀU nút 'Tải xuống' (đã gặp thật: ứng viên có
        3 file đã tải lên + 1 CV tự xuất) — phải trả về đủ theo đúng thứ tự ưu
        tiên (.btn-download-cv trước) để download() thử lần lượt, không dừng
        ở link đầu và cũng không lặp lại link trùng."""
        html = (
            '<a class="btn-download" href="/tool/download?l=https%3A%2F%2Fadmin.jobsgo.vn%2Fa.pdf">x</a>'
            '<a class="btn-download" href="/tool/download?l=https%3A%2F%2Fadmin.jobsgo.vn%2Fa.pdf">x</a>'
            '<a class="btn-download-cv" href="/tool/download?l=https%3A%2F%2Fjobsgo.vn%2Fgen.pdf">x</a>'
        )
        self.assertEqual(self.provider._extract_cdn_urls(html), [
            "https://jobsgo.vn/gen.pdf",     # .btn-download-cv ưu tiên trước
            "https://admin.jobsgo.vn/a.pdf",  # .btn-download, trùng thì chỉ lấy 1
        ])

    def test_concurrency_is_serial(self):
        self.assertEqual(self.provider.concurrency_limit(), 1)

    def test_never_headless(self):
        """Cloudflare chặn Chrome headless trên site này - đã kiểm chứng thực tế."""
        self.provider.cfg = SimpleNamespace(
            jobsgo_email="employer@example.test", jobsgo_password="secret",
            jobsgo_profile_dir=lambda: "C:/tmp/jobsgo_profile")
        cfg = self.provider._browser_cfg()
        self.assertFalse(cfg.headless)

    def test_wait_download_buttons_returns_once_href_is_real(self):
        """Hồi quy: bản trước chỉ chờ PHẦN TỬ tồn tại (luôn đúng ngay lập tức
        vì nút placeholder `.btn-download-cv` có sẵn trong HTML) nên trả về
        quá sớm, trước khi AJAX `/dashboard/get-cv-file` kịp gán href thật —
        đã gặp thật với 2 hồ sơ khai trực tiếp trên form (mục 37.1). Giờ phải
        chờ tới khi CÓ MỘT phần tử với href chứa cả 'tool/download' và 'l='."""
        class FakeEl:
            def __init__(self, href):
                self._href = href

            def get_attribute(self, name):
                return self._href if name == "href" else None

        class FakeDriver:
            current_url = "https://employer.jobsgo.vn/candidate/detail?cid=x"

            def __init__(self):
                self.calls = 0

            def find_elements(self, _by, selector):
                if selector == "input[type='password']":
                    return []  # không ở trang đăng nhập
                self.calls += 1
                # 2 lần đầu vẫn là placeholder "#" (như trong lúc AJAX chưa xong).
                if self.calls < 3:
                    return [FakeEl("https://employer.jobsgo.vn/candidate/detail?cid=x#")]
                return [FakeEl("https://employer.jobsgo.vn/tool/download?n=A&l=https%3A%2F%2Fx%2Ff.pdf")]

        self.provider.driver = FakeDriver()
        started = time.time()
        self.provider._wait_download_buttons(seconds=5)
        self.assertLess(time.time() - started, 4.5)
        self.assertGreaterEqual(self.provider.driver.calls, 3)

    def test_download_ignores_has_file_flag(self):
        """`_has_file` chỉ để hiển thị, KHÔNG được dùng để chặn download() nữa
        — đã gặp thật: hồ sơ '0 file' (chưa tải CV lên) vẫn có nút xuất CV từ
        dữ liệu khai trực tiếp trên hồ sơ (giống VietnamWorks)."""
        data, error = self.provider.download({"cv_id": "x", "_has_file": False, "cv_url": ""})
        self.assertIsNone(data)
        self.assertIn("Thiếu đường dẫn hồ sơ", error)
        self.assertNotIn("chưa đính kèm", error)

    def test_click_download_button_skips_placeholder_href(self):
        """Hồi quy sự cố thật: hồ sơ có ĐỒNG THỜI nút `.btn-download-cv` còn
        href="#" (chưa được JS gán, hoặc hồ sơ dùng nút khác) và nút
        `.btn-download` đã có href thật — phải bấm đúng nút có href thật,
        không bấm nhầm nút "#" rồi chờ vô ích. Xem
        KINH_NGHIEM_TRIEN_KHAI_CAC_KENH_TUYEN_DUNG.md mục 37.1."""
        class FakeEl:
            def __init__(self, href, displayed=True):
                self._href = href
                self._displayed = displayed

            def is_displayed(self):
                return self._displayed

            def get_attribute(self, name):
                return self._href if name == "href" else None

        placeholder = FakeEl("https://employer.jobsgo.vn/candidate/detail?cid=x#")
        real = FakeEl("https://employer.jobsgo.vn/tool/download?n=A&l=https%3A%2F%2Fjobsgo.vn%2Ff.docx")
        clicked = []

        class FakeDriver:
            def execute_cdp_cmd(self, *_a, **_k):
                pass

            def find_elements(self, _by, selector):
                if selector == "a.btn-download-cv[href]":
                    return [placeholder]
                if selector == "a.btn-download[href]":
                    return [real]
                return []

            def execute_script(self, _script, element):
                clicked.append(element)

        folder = tempfile.mkdtemp(prefix="jobsgo-test-")
        try:
            with open(os.path.join(folder, "cv.docx"), "wb") as handle:
                handle.write(b"PK\x03\x04fake")
            self.provider.driver = FakeDriver()
            ok = self.provider._click_download_button(folder)
            self.assertTrue(ok)
            self.assertEqual(clicked, [real])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_click_download_button_returns_false_when_all_hrefs_are_placeholders(self):
        class FakeEl:
            def is_displayed(self):
                return True

            def get_attribute(self, name):
                return "https://employer.jobsgo.vn/candidate/detail?cid=x#" if name == "href" else None

        class FakeDriver:
            def execute_cdp_cmd(self, *_a, **_k):
                pass

            def find_elements(self, _by, _selector):
                return [FakeEl()]

        self.provider.driver = FakeDriver()
        folder = tempfile.mkdtemp(prefix="jobsgo-test-")
        try:
            self.assertFalse(self.provider._click_download_button(folder))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_parse_detail_fields_reads_lam_viec_tai_as_desired_location(self):
        """Trang chi tiết JobsGO gọi nơi làm việc mong muốn là "Làm việc tại"
        (mỗi kênh gọi một kiểu). Cấu trúc thật:
        <li><strong>Nhãn:</strong><span>giá trị</span></li> (đã kiểm chứng 5/5
        hồ sơ). Bóc đúng trường này + địa chỉ/năm sinh/giới tính."""
        html = """
        <h3>Thông Tin Cơ Bản</h3>
        <ul>
          <li><strong>Năm sinh:</strong> <span>2004 (22 tuổi)</span></li>
          <li><strong>Giới tính:</strong> <span>Nữ</span></li>
          <li><strong>Số điện thoại:</strong> <span>086.589.7616</span></li>
          <li><strong>Làm việc tại:</strong> <span>Bình Dương, Hồ Chí Minh</span></li>
          <li><strong>Email:</strong> <span>hnhi311204@gmail.com</span></li>
          <li><strong>Địa chỉ:</strong> <span>Quận 7, Hồ Chí Minh</span></li>
        </ul>
        """
        fields = JobsGoProvider._parse_detail_fields(html)
        self.assertEqual(fields["desired_location"], "Bình Dương, Hồ Chí Minh")
        self.assertEqual(fields["address"], "Quận 7, Hồ Chí Minh")
        self.assertEqual(fields["birth_year"], "2004")
        self.assertEqual(fields["gender"], "Nữ")

    def test_parse_detail_fields_skips_empty_placeholder(self):
        html = ("<li><strong>Làm việc tại:</strong> <span>Chưa cập nhật</span></li>"
                "<li><strong>Địa chỉ:</strong> <span>-</span></li>")
        self.assertEqual(JobsGoProvider._parse_detail_fields(html), {})

    def test_parse_detail_fields_reads_position_and_work_history(self):
        """Vị trí ứng tuyển nằm ở `.candidate-position` (header hồ sơ), ngoài
        mục "Thông Tin Cơ Bản"; chức danh/công ty gần nhất ở `#tab-qua-trinh`;
        học vấn placeholder ("Chưa có thông tin học vấn") phải bị bỏ."""
        html = """
        <div class="candidate-info">
          <h1>Hoàng Ngọc Hân Nhi</h1>
          <div class="candidate-position"> CHUYÊN VIÊN PHÁT TRIỂN KHDN LỚN </div>
        </div>
        <div class="cv-section" id="tab-qua-trinh"><h2>Quá trình làm việc</h2>
          <div class="resume-item">
            <h4>Thực tập sinh quan hệ khách hàng doanh nghiệp</h4>
            <small>Ngân hàng TMCP Quân đội</small>
            <h5>2025-08 2025-11</h5>
          </div>
        </div>
        <div class="cv-section" id="tab-hoc-van"><h2>Học vấn</h2>
          <p class="text-muted">Chưa có thông tin học vấn</p>
        </div>
        """
        fields = JobsGoProvider._parse_detail_fields(html)
        self.assertEqual(fields["position"], "CHUYÊN VIÊN PHÁT TRIỂN KHDN LỚN")
        self.assertEqual(fields["current_title"],
                         "Thực tập sinh quan hệ khách hàng doanh nghiệp")
        self.assertEqual(fields["last_company"], "Ngân hàng TMCP Quân đội")
        self.assertNotIn("education", fields)

    def test_download_enriches_item_with_desired_location(self):
        """`download()` khi mở trang chi tiết để tìm nút tải phải tiện thể điền
        `desired_location` vào item (item được engine upsert sau đó)."""
        item = {"cv_id": "x", "cv_url": "https://employer.jobsgo.vn/candidate/detail?cid=a&jid=b"}
        detail_html = ('<li><strong>Làm việc tại:</strong> <span>Đà Nẵng</span></li>'
                       '<a class="btn-download-cv" href="/tool/download?l=https%3A%2F%2Fx%2Ff.pdf">Tải</a>')

        self.provider.driver = SimpleNamespace(
            current_url="https://employer.jobsgo.vn/candidate/detail?cid=a&jid=b",
            page_source=detail_html,
            find_elements=lambda *_a, **_k: [])
        self.provider._wait_download_buttons = lambda *a, **k: None
        self.provider._on_login_page = lambda: False

        class _Resp:
            status_code = 200
            content = b"%PDF-1.4 fake"
            headers = {"Content-Type": "application/pdf"}

        self.provider._session = lambda: SimpleNamespace(get=lambda *a, **k: _Resp())
        import app.providers.jobsgo as mod
        original_safe_get = mod.safe_get
        mod.safe_get = lambda *a, **k: None
        try:
            data, ext = self.provider.download(item)
        finally:
            mod.safe_get = original_safe_get
        self.assertIsNotNone(data)
        self.assertEqual(item["desired_location"], "Đà Nẵng")

    def test_iter_pages_raises_on_empty_page(self):
        self.provider._last_page = 2
        self.provider._first_page_items = [{"cv_id": "1"}]
        self.provider._goto_list_page = lambda page: "<html><body>no rows</body></html>"
        it = self.provider.iter_pages(1, 2)
        self.assertEqual(next(it)[0], 1)
        with self.assertRaises(RuntimeError):
            next(it)


if __name__ == "__main__":
    unittest.main()
