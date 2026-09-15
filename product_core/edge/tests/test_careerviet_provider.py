import json
import unittest
from types import SimpleNamespace

from app.providers.careerviet import CareerVietProvider
from app.providers.base import LoginError


class CareerVietProviderTests(unittest.TestCase):
    def setUp(self):
        cfg = SimpleNamespace(careerviet_email="", careerviet_password="",
                              careerviet_profile_dir="unused", headless=True,
                              chrome_version=0)
        self.provider = CareerVietProvider(cfg, log=lambda _message: None)

    def test_format_districts_matches_ui_desired_location(self):
        """`resume_districts` (địa điểm làm việc mong muốn) - key JSON đã xác
        nhận bằng dump thật. Ghép "Tỉnh (quận...)" như UI hiển thị, tên tỉnh
        chuẩn hoá về dạng chuẩn ("TP HCM" -> "Hồ Chí Minh")."""
        value = [{"location_id": 4, "location_name": "Hà Nội",
                  "districts": [{"district_id": None, "district_name_vn": "Tất cả quận/huyện"}]},
                 {"location_id": 79, "location_name": "TP HCM", "districts": []}]
        self.assertEqual(CareerVietProvider._format_districts(value),
                         "Hà Nội (Tất cả quận/huyện); Hồ Chí Minh")
        self.assertEqual(CareerVietProvider._format_districts(None), "")
        self.assertEqual(CareerVietProvider._format_districts([]), "")

    def test_format_named_list_joins_industries_and_languages(self):
        self.assertEqual(
            CareerVietProvider._format_named_list(
                [{"industry_id": 19, "industry_name_vn": "Ngân hàng"},
                 {"industry_id": 5, "industry_name_vn": "Tài chính"}], "industry_name_vn"),
            "Ngân hàng, Tài chính")
        self.assertEqual(
            CareerVietProvider._format_named_list(
                [{"type": 8, "level": 2, "certification": "Tiếng Việt"}], "certification"),
            "Tiếng Việt")
        self.assertEqual(CareerVietProvider._format_named_list(None, "x"), "")

    def test_load_detail_maps_confirmed_desired_fields(self):
        """Key đã xác nhận (dump `detail` thật 2026-09-05): `resume_districts`,
        `resume_level_name_vn` (cấp bậc MONG MUỐN, khác
        `resume_present_level_name_vn` = hiện tại), `resume_industries`,
        `resume_languages`."""
        detail = {
            "jobseeker_fullname": "Test", "resume_id": "R1",
            "resume_districts": [{"location_name": "Khánh Hòa",
                                  "districts": [{"district_name_vn": "Tất cả quận/huyện"}]}],
            "resume_level_name_vn": "Nhân viên",
            "resume_present_level_name_vn": "Trưởng phòng",
            "resume_industries": [{"industry_name_vn": "Thu mua / Vật tư"}],
            "resume_languages": [{"certification": "Tiếng Anh"}],
        }
        self.provider._request = lambda *a, **k: SimpleNamespace(
            status_code=200, json=lambda: {"data": detail})
        self.provider._encode_id = lambda x: x
        item = {"resume_id": "R1", "cv_id": "F1"}
        self.provider._load_detail(item)
        self.assertEqual(item["desired_location"], "Khánh Hòa (Tất cả quận/huyện)")
        self.assertEqual(item["desired_level"], "Nhân viên")
        self.assertEqual(item["desired_position"], "Thu mua / Vật tư")
        self.assertEqual(item["foreign_language"], "Tiếng Anh")
        self.assertEqual(item["job_level"], "Trưởng phòng")  # hiện tại, không lẫn với mong muốn

    def test_application_id_is_not_resume_id(self):
        item = self.provider._normalize({
            "folder_resume_id": 991, "resume_id": 42, "job_id": 7,
            "jobseeker_fullname": "Nguyen Van A",
        })
        self.assertEqual("991", item["cv_id"])
        self.assertEqual("42", item["resume_id"])
        self.assertEqual("7", item["campaign_id"])

    def test_normalize_keeps_shared_database_fields(self):
        item = self.provider._normalize({
            "folder_resume_id": 12, "resume_id": 13, "jobseeker_id": 14,
            "jobseeker_fullname": "Tran B", "jobseeker_email": "b@example.test",
            "resume_last_job": "Data Analyst", "resume_last_company": "Example",
            "resume_year_of_experience": 5, "degree_name_vn": "Đại học",
            "resume_targetjob_salary": 1000, "resume_targetjob_to_salary": 1500,
            "resume_salary_unit": "usd", "created_at": "2026-08-10T07:32:47.000Z",
        })
        self.assertEqual("10/08/2026 14:32", item["applied_at"])
        self.assertEqual("2026-08-10 14:32:47", item["applied_ts"])
        self.assertEqual("1000 - 1500 USD", item["expected_salary"])
        self.assertEqual("Data Analyst", item["current_title"])
        self.assertEqual("14", item["candidate_id"])
        self.assertEqual(0, item["detail_loaded"])
        self.assertEqual("Tran B", json.loads(item["source_payload"])["jobseeker_fullname"])

    def test_full_backup_has_gentle_limits(self):
        self.provider.run_mode = "tatca"
        self.assertEqual(2, self.provider.concurrency_limit())
        self.assertGreaterEqual(self.provider.minimum_item_delay_ms(), 500)
        self.provider.run_mode = "moi"
        self.assertEqual(4, self.provider.concurrency_limit())

    def test_careerviet_numeric_id_encoding(self):
        self.assertEqual("3810C92F", self.provider._encode_id(40624175))
        self.assertEqual("3810C92F", self.provider._encode_id("3810c92f"))

    def test_last_page_and_exact_range_total_are_exposed_to_engine(self):
        self.provider._total = 37352
        self.provider._last_page = 1868
        self.assertEqual(1868, self.provider.last_page)
        self.assertEqual(20, self.provider.range_total(1, 1))
        self.assertEqual(12, self.provider.range_total(1868, 1868))

    def test_invalid_retry_after_uses_bounded_backoff(self):
        response = SimpleNamespace(headers={"Retry-After": "invalid"})
        delay = self.provider._retry_delay(response, 2)
        self.assertGreater(delay, 4)
        self.assertLessEqual(delay, 30)

    def test_unrecoverable_401_is_a_login_error_not_a_cv_error(self):
        response = SimpleNamespace(status_code=401, headers={})
        session = SimpleNamespace(request=lambda *args, **kwargs: response)
        self.provider._token = "expired"
        self.provider._session = lambda: session
        self.provider._refresh = lambda _rejected="": False
        self.provider._wait_throttle = lambda: None
        with self.assertRaises(LoginError):
            self.provider._request("GET", "https://internal-api.careerviet.vn/test")

    def test_empty_middle_page_keeps_checkpoint_retryable(self):
        self.provider._last_page = 10
        self.provider._first_page = [{"cv_id": "first"}]
        self.provider._fetch_page = lambda page: ([], {"pageCount": 10})
        pages = self.provider.iter_pages(2, 5)
        with self.assertRaises(RuntimeError):
            next(pages)

    def test_detail_maps_high_value_fields_to_shared_schema(self):
        detail = {"data": {
            "jobseeker_fullname": "Candidate",
            "jobseeker_mobile": "0900000000",
            "jobseeker_birthday": "1990-05-20",
            "jobseeker_address": "Ha Noi",
            "jobseeker_location_name_vn": "Hà Nội",
            "jobseeker_district_name_vn": "Cầu Giấy",
            "resume_level_name_vn": "Trưởng nhóm",
            "resume_degree_name_vn": "Đại học",
            "resume_target_job_salary": "1000",
            "resume_target_job_to_salary": "1500",
            "resume_salary_unit": "usd",
            "resume_attachment_url": "https://files.careerviet.vn/cv/test.pdf",
        }}
        response = SimpleNamespace(status_code=200, json=lambda: detail)
        self.provider._request = lambda *args, **kwargs: response
        item = {"cv_id": "12", "resume_id": "ABC123", "source_payload": "{}"}
        self.provider._load_detail(item)
        self.assertEqual("1990", item["birth_year"])
        self.assertEqual("Cầu Giấy", item["district"])
        self.assertEqual("Trưởng nhóm", item["job_level"])
        self.assertEqual("1000 - 1500 USD", item["expected_salary"])
        self.assertEqual("test.pdf", item["attachment_name"])
        self.assertEqual(1, item["detail_loaded"])

    def test_login_sends_required_careerviet_origin(self):
        captured = {}
        response = SimpleNamespace(status_code=200, cookies=[])

        class Session:
            def post(self, url, **kwargs):
                captured.update(kwargs)
                return response

        self.provider.cfg.careerviet_email = "user"
        self.provider.cfg.careerviet_password = "password"
        self.provider._cookie_session = lambda: Session()
        self.provider._install_response_cookies = lambda _response: True
        self.provider._login()
        self.assertEqual("https://careerviet.vn", captured["headers"]["Origin"])

    def test_auth_cookies_replace_stale_domain_and_keep_expiry(self):
        calls = []

        class Driver:
            def delete_cookie(self, name):
                calls.append(("delete", name))
            def add_cookie(self, cookie):
                calls.append(("add", cookie))

        cookie = SimpleNamespace(
            name="employer-tokens", value="fresh", domain="careerviet.vn", path="/",
            secure=True, expires=1890000000, _rest={"HttpOnly": None, "SameSite": "lax"})
        self.provider.driver = Driver()
        self.provider._install_response_cookies(SimpleNamespace(cookies=[cookie]))
        self.assertEqual(("delete", "employer-tokens"), calls[0])
        installed = calls[1][1]
        self.assertEqual("careerviet.vn", installed["domain"])
        self.assertEqual(1890000000, installed["expiry"])
        self.assertEqual("Lax", installed["sameSite"])

    def test_browser_check_json_sets_current_token_without_extra_http(self):
        body = json.dumps({"token": {"accessToken": "fresh-token"}, "user": {"id": "1"}})

        class Driver:
            def execute_script(self, script):
                return body if "innerText" in script else "Browser UA"
            def get_cookies(self):
                return [{"name": "employer-session", "value": "session"}]

        self.provider.driver = Driver()
        self.assertTrue(self.provider._read_browser_check_session())
        self.assertEqual("fresh-token", self.provider._token)


if __name__ == "__main__":
    unittest.main()
