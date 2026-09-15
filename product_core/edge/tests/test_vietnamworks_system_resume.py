import unittest
from types import SimpleNamespace

from app.providers.vietnamworks import VietnamWorksProvider


class VietnamWorksSystemResumeTests(unittest.TestCase):
    def setUp(self):
        self.provider = VietnamWorksProvider(SimpleNamespace(), log=lambda _message: None)

    def test_scrape_general_panel_reads_desired_fields_from_ui_dom(self):
        """Panel "Thông tin chung" của trang UI (server-render) chứa các trường
        query GraphQL đang dùng KHÔNG trả: nơi làm việc mong muốn, tình trạng
        hôn nhân, cấp bậc mong muốn, ngoại ngữ, lương hiện tại. Cấu trúc thật
        (trang đã lưu): <div class="discriptions"><div class="titleContent">
        Nhãn</div><div class="valueContent">Giá trị</div></div>, có bản viewPC
        rồi viewMobile lặp lại — chỉ lấy lần đầu."""
        dom = """
        <div class="viewPC"><div class="viewExpectedSalary">
            <div class="titleContentSalary">Mức lương hiện tại</div>
            <div class="valueContentSalary">1,200 (USD/tháng)</div></div>
          <div class="content">
            <div class="discriptions"><div class="titleContent">Vị trí hiện tại</div>
              <div class="valueContent">_</div></div>
            <div class="discriptions"><div class="titleContent">Cấp bậc mong muốn</div>
              <div class="valueContent">Trưởng phòng</div></div>
            <div class="discriptions"><div class="titleContent">Tình trạng hôn nhân</div>
              <div class="valueContent">Đã kết hôn</div></div>
            <div class="discriptions"><div class="titleContent">Ngày sinh</div>
              <div class="valueContent">20/11/1990</div></div>
            <div class="discriptions"><div class="titleContent">Nơi làm việc mong muốn</div>
              <div class="valueContent">Hà Nội</div></div>
            <div class="discriptions"><div class="titleContent">Trình độ ngoại ngữ</div>
              <div class="valueContent"><div class="valueContentlanguageName">Tiếng Anh</div></div></div>
          </div></div>
        <div class="viewMobile"><div class="discriptions"><div class="titleContent">Nơi làm việc mong muốn</div>
            <div class="valueContent">SAI - bản mobile lặp lại</div></div></div>
        """
        provider = VietnamWorksProvider(SimpleNamespace(), log=lambda _m: None)
        item = {"cv_url": "https://employer.vietnamworks.com/v3/application/detail/1/2"}
        provider._apply_general_panel(dom, item)
        self.assertEqual(item["desired_location"], "Hà Nội")
        self.assertEqual(item["marital_status"], "Đã kết hôn")
        self.assertEqual(item["desired_level"], "Trưởng phòng")
        self.assertEqual(item["foreign_language"], "Tiếng Anh")
        self.assertEqual(item["current_salary"], "1,200 (USD/tháng)")
        self.assertEqual(item["birth_year"], "1990")   # "Ngày sinh 20/11/1990" -> chỉ lấy năm
        self.assertNotIn("SAI", item["desired_location"])
        self.assertNotIn("current_title", item)  # "Vị trí hiện tại" = "_" -> bỏ qua placeholder

    def test_apply_general_panel_reads_english_labels(self):
        """Tài khoản để giao diện tiếng Anh — panel dùng nhãn EN. Đã gặp thật
        (log 2026-09-06): 'Expected job location', 'Martial status' (VNW gõ sai
        chính tả), 'Languages', 'Expected job level', 'Current salary'."""
        dom = """
        <div class="content">
          <div class="discriptions"><div class="titleContent">Current position</div>
            <div class="valueContent">_</div></div>
          <div class="discriptions"><div class="titleContent">Expected job level</div>
            <div class="valueContent">Manager</div></div>
          <div class="discriptions"><div class="titleContent">Martial status</div>
            <div class="valueContent">Married</div></div>
          <div class="discriptions"><div class="titleContent">Expected job location</div>
            <div class="valueContent">Ho Chi Minh</div></div>
          <div class="discriptions"><div class="titleContent">Languages</div>
            <div class="valueContent">English - Advanced</div></div>
          <div class="discriptions"><div class="titleContent">Current salary</div>
            <div class="valueContent">Add number</div></div>
        </div>
        """
        provider = VietnamWorksProvider(SimpleNamespace(), log=lambda _m: None)
        item = {}
        provider._apply_general_panel(dom, item)
        self.assertEqual(item["desired_location"], "Hồ Chí Minh")   # chuẩn hoá về tên VN
        self.assertEqual(item["desired_level"], "Manager")
        self.assertEqual(item["marital_status"], "Married")
        self.assertEqual(item["foreign_language"], "English - Advanced")
        self.assertNotIn("current_salary", item)   # "Add number" là placeholder -> bỏ
        self.assertNotIn("current_title", item)    # "_" -> bỏ

    def test_scrape_general_panel_is_silent_without_driver(self):
        provider = VietnamWorksProvider(SimpleNamespace(), log=lambda _m: None)
        provider.driver = None
        item = {"cv_url": "x"}
        provider._scrape_general_panel(item)  # không ném lỗi
        self.assertNotIn("desired_location", item)
        self.assertEqual(item["detail_loaded"], 1)

    def test_system_export_url_matches_vietnamworks_download_button(self):
        item = {"cv_id": "63214267", "resume_id": "7298135", "profile_type": "1"}
        url = self.provider._system_export_url(item, {"appTypeSource": 1})
        self.assertEqual(
            "https://employer.vietnamworks.com/v2/application/download/"
            "7298135/1/63214267/1?source=ams_screening&application_score=null",
            url)
        self.assertIn("/7298135/1/63214267/1", self.provider._system_export_url(
            item, {"appTypeSource": 1.0}))

    def test_form_resume_uses_system_export_before_stale_attachment(self):
        self.provider._load_detail = lambda item: {
            "canDownload": True,
            "isAttached": 0,
            "appTypeSource": 1,
            "attachmentPath": "https://employer.vietnamworks.com/view-attach/stale",
        }
        calls = []

        def try_url(item, url, *, click_attachment):
            calls.append((url, click_attachment))
            return b"%PDF-1.7\nsystem", ".pdf", "", 200

        self.provider._try_download_url = try_url
        item = {"cv_id": "63214267", "resume_id": "7298135", "profile_type": "1",
                "fullname": "Candidate"}
        data, ext = self.provider.download(item)
        self.assertEqual(".pdf", ext)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertIn("/v2/application/download/7298135/1/63214267/1", calls[0][0])
        self.assertFalse(calls[0][1])
        self.assertEqual("application/pdf", item["attachment_mime"])

    def test_uploaded_attachment_can_fallback_to_system_export_after_404(self):
        self.provider._load_detail = lambda item: {
            "canDownload": True,
            "isAttached": 1,
            "appTypeSource": 1,
            "attachmentPath": "https://employer.vietnamworks.com/view-attach/missing",
        }
        calls = []

        def try_url(item, url, *, click_attachment):
            calls.append(url)
            if "view-attach" in url:
                return None, None, "HTTP 404", 404
            return b"%PDF-1.7\ngenerated", ".pdf", "", 200

        self.provider._try_download_url = try_url
        data, ext = self.provider.download({
            "cv_id": "12", "resume_id": "34", "profile_type": "1"})
        self.assertEqual(".pdf", ext)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(2, len(calls))
        self.assertIn("view-attach", calls[0])
        self.assertIn("/v2/application/download/34/1/12/1", calls[1])


if __name__ == "__main__":
    unittest.main()
