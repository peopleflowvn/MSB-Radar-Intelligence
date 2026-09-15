# -*- coding: utf-8 -*-
"""Kiểm thử việc chuyển state cục bộ từ GenSync Radar sang MSB Radar.

Rủi ro thật mà bộ test này canh: profile Chrome của 5 cổng tuyển dụng nằm trong
thư mục state. Mất chúng nghĩa là phải đăng nhập lại và qua CAPTCHA thủ công
từng tài khoản. Vì vậy mọi nhánh — kể cả nhánh thất bại — đều phải giữ nguyên
dữ liệu và không được ném lỗi ra ngoài.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import shutil
from unittest.mock import patch

from app import state_paths


def _seed_legacy(base, folder="GenSyncRadar"):
    """Dựng một thư mục state cũ có nội dung như thật."""
    legacy = os.path.join(base, folder)
    os.makedirs(os.path.join(legacy, "chrome_profile", "account_abc123"), exist_ok=True)
    with open(os.path.join(legacy, "secrets.json"), "w", encoding="utf-8") as f:
        f.write('{"password": "blob-da-ma-hoa"}')
    with open(os.path.join(legacy, "chrome_profile", "account_abc123", "Cookies"),
              "w", encoding="utf-8") as f:
        f.write("phien-dang-nhap")
    return legacy


class StateMigrationTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        state_paths.reset_cache()
        self.addCleanup(state_paths.reset_cache)
        # Bảo đảm test không bao giờ đọc biến môi trường thật của máy dev.
        patcher = patch.dict(os.environ, {state_paths.MIGRATION_ENV: ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def target(self):
        return os.path.join(self.base, state_paths.APP_STATE_FOLDER)

    # ---------- resolve: thuần đường dẫn, không được chạm đĩa ----------

    def test_resolve_khong_tao_thu_muc(self):
        resolved = state_paths.resolve_state_dir(self.base)
        self.assertEqual(resolved, self.target)
        self.assertFalse(os.path.exists(resolved),
                         "resolve_state_dir không được tạo thư mục")

    def test_resolve_uu_tien_thu_muc_moi(self):
        os.makedirs(self.target)
        _seed_legacy(self.base)
        self.assertEqual(state_paths.resolve_state_dir(self.base), self.target)

    def test_resolve_lui_ve_thu_muc_cu_khi_chua_chuyen(self):
        legacy = _seed_legacy(self.base)
        self.assertEqual(state_paths.resolve_state_dir(self.base), legacy)

    # ---------- migrate: di chuyển thật ----------

    def test_chuyen_giu_nguyen_noi_dung(self):
        _seed_legacy(self.base)
        moved = state_paths.migrate_legacy_state(self.base)

        self.assertEqual(moved, self.target)
        with open(os.path.join(self.target, "secrets.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"password": "blob-da-ma-hoa"}')
        cookies = os.path.join(self.target, "chrome_profile", "account_abc123", "Cookies")
        with open(cookies, encoding="utf-8") as f:
            self.assertEqual(f.read(), "phien-dang-nhap")

    def test_de_lai_ghi_chu_o_cho_cu(self):
        legacy = _seed_legacy(self.base)
        state_paths.migrate_legacy_state(self.base)

        pointer = os.path.join(legacy, state_paths._POINTER_NAME)
        self.assertTrue(os.path.isfile(pointer), "phải để lại ghi chú chỉ đường")
        with open(pointer, encoding="utf-8-sig") as f:
            self.assertIn(self.target, f.read())
        # Ghi chú không được kéo theo dữ liệu cũ.
        self.assertFalse(os.path.exists(os.path.join(legacy, "secrets.json")))

    def test_khong_chuyen_khi_da_co_thu_muc_moi(self):
        os.makedirs(self.target)
        legacy = _seed_legacy(self.base)

        self.assertIsNone(state_paths.migrate_legacy_state(self.base))
        self.assertTrue(os.path.isfile(os.path.join(legacy, "secrets.json")),
                        "state cũ phải được giữ nguyên, không ghi đè")

    def test_khong_lam_gi_khi_khong_co_state_cu(self):
        self.assertIsNone(state_paths.migrate_legacy_state(self.base))
        self.assertFalse(os.path.exists(self.target))

    def test_goi_hai_lan_van_on_dinh(self):
        _seed_legacy(self.base)
        first = state_paths.migrate_legacy_state(self.base)
        second = state_paths.migrate_legacy_state(self.base)

        self.assertEqual(first, self.target)
        self.assertIsNone(second, "lần thứ hai không được di chuyển gì thêm")
        self.assertTrue(os.path.isfile(os.path.join(self.target, "secrets.json")))

    # ---------- nhánh thất bại: tuyệt đối không được mất dữ liệu ----------

    def test_that_bai_khi_doi_ten_van_giu_du_lieu(self):
        """Chrome đang giữ file trong profile -> os.rename ném OSError."""
        legacy = _seed_legacy(self.base)

        with patch("app.state_paths.os.rename", side_effect=OSError("file dang mo")):
            moved = state_paths.migrate_legacy_state(self.base)

        self.assertIsNone(moved)
        self.assertTrue(os.path.isfile(os.path.join(legacy, "secrets.json")),
                        "thất bại phải để nguyên hiện trạng")
        # Phiên này vẫn phải chạy được bằng thư mục cũ.
        self.assertEqual(state_paths.resolve_state_dir(self.base), legacy)

    def test_tat_bang_bien_moi_truong(self):
        legacy = _seed_legacy(self.base)
        with patch.dict(os.environ, {state_paths.MIGRATION_ENV: "off"}):
            self.assertIsNone(state_paths.migrate_legacy_state(self.base))
        self.assertTrue(os.path.isfile(os.path.join(legacy, "secrets.json")))

    # ---------- cache ----------

    def test_local_state_dir_nho_ket_qua(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": self.base}):
            first = state_paths.local_state_dir()
            os.makedirs(self.target, exist_ok=True)
            self.assertEqual(state_paths.local_state_dir(), first,
                             "phải trả kết quả đã nhớ, không tính lại")
            state_paths.reset_cache()
            self.assertEqual(state_paths.local_state_dir(), self.target)


class ConfigUsesStatePathsTest(unittest.TestCase):
    """config.py phải lấy mọi đường dẫn state từ state_paths, không hardcode."""

    def test_khong_con_ten_gensync_trong_config(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "app", "config.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("GenSyncRadar", source)
        self.assertNotIn("GENSYNC_", source)

    def test_profile_dir_nam_duoi_state_dir(self):
        from app.config import AppConfig
        cfg = AppConfig()
        state = state_paths.local_state_dir()
        for getter in (cfg.profile_dir, cfg.vietnamworks_profile_dir,
                       cfg.careerviet_profile_dir, cfg.vieclam24h_profile_dir,
                       cfg.itviec_profile_dir, cfg.joboko_profile_dir,
                       cfg.jobsgo_profile_dir):
            self.assertTrue(getter().startswith(state),
                            f"{getter.__name__} phải nằm dưới {state}")

    def test_refresh_state_paths_cap_nhat_secret_path(self):
        from app import config
        with patch("app.config.local_state_dir", return_value=r"X:\state-moi"):
            config.refresh_state_paths()
            self.assertEqual(config.SECRET_PATH, os.path.join(r"X:\state-moi", "secrets.json"))
        config.refresh_state_paths()   # trả lại giá trị thật cho các test sau


if __name__ == "__main__":
    unittest.main()
