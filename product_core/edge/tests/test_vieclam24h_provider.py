import json
import threading
import unittest
from types import SimpleNamespace

from app.providers.vieclam24h import Vieclam24hProvider


class Vieclam24hDesiredLocationTests(unittest.TestCase):
    """API danh sách Vieclam24h chỉ trả `desired_location` là DANH SÁCH
    province_id (số) và `marital_status` là mã số - phải giải mã sang tên.
    Bảng tra tỉnh lấy từ `provinces` trong __NEXT_DATA__ trang quản trị (key
    đã xác nhận bằng khảo sát thật 2026-09-05)."""

    def setUp(self):
        cfg = SimpleNamespace(vieclam24h_email="", vieclam24h_password="")
        self.provider = Vieclam24hProvider.__new__(Vieclam24hProvider)
        self.provider.cfg = cfg
        self.provider.log = lambda *_a, **_k: None
        self.provider._driver_lock = threading.RLock()
        self.provider._province_map = {}

    def test_load_province_map_extracts_from_next_data(self):
        next_data = {"props": {"pageProps": {"config": {"provinces": [
            {"id": 119, "code": "vi.BD", "name": "Bình Dương"},
            {"id": 104, "code": "vi.DNG", "name": "Đà Nẵng"},
            {"id": 73, "code": "vi.HN", "name": "Hà Nội"},
        ]}}}}
        html = ('<html><body><script id="__NEXT_DATA__" type="application/json">'
                + json.dumps(next_data, ensure_ascii=False)
                + '</script></body></html>')
        self.provider.driver = SimpleNamespace(page_source=html)
        self.provider._load_province_map()
        self.assertEqual(self.provider._province_map[119], "Bình Dương")
        self.assertEqual(self.provider._province_map[104], "Đà Nẵng")

    def test_resolve_desired_location_maps_ids_to_names(self):
        self.provider._province_map = {119: "Bình Dương", 104: "Đà Nẵng", 122: "TP.HCM"}
        self.assertEqual(
            self.provider._resolve_desired_location({"desired_location": [104, 119]}),
            "Đà Nẵng, Bình Dương")
        # id lạ -> bỏ qua, không hiện mã số
        self.assertEqual(
            self.provider._resolve_desired_location({"desired_location": [999]}), "")
        self.assertEqual(
            self.provider._resolve_desired_location({"desired_location": None}), "")

    def test_resolve_returns_empty_when_no_province_map(self):
        self.provider._province_map = {}
        self.assertEqual(
            self.provider._resolve_desired_location({"desired_location": [119]}), "")

    def test_normalize_fills_desired_location_and_marital_status(self):
        self.provider._province_map = {104: "Đà Nẵng"}
        row = {
            "id": "1", "seeker_info": {"name": "Test", "marital_status": 2},
            "resume_info": {}, "job_info": {}, "desired_location": [104],
        }
        item = self.provider._normalize(row)
        self.assertEqual(item["desired_location"], "Đà Nẵng")
        self.assertEqual(item["marital_status"], "Đã kết hôn")


if __name__ == "__main__":
    unittest.main()
