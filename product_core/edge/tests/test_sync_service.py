# -*- coding: utf-8 -*-
"""Đường dây đồng bộ Edge → Hub thật sự được nối vào ứng dụng.

Bài quan trọng nhất ở đây là `test_web_api_co_du_cau_noi_dong_bo`.

Trước bản này `app/sync/` đầy đủ và có test — client, runner, payload đều đúng —
nhưng **không ai gọi**. `grep` toàn bộ mã ứng dụng chỉ tìm thấy đúng một lời gọi
(`recover_sync_queue`), không có bộ lập lịch, không cầu nối JS, không màn hình.
Edge thu CV về SQLite rồi dừng ở đó.

Test đơn vị của `runner` không phát hiện được điều đó, vì chúng gọi thẳng
`runner`. Chỉ bài kiểm **đường dây** mới bắt được, nên nó tồn tại ở đây.
"""
import threading
import unittest
from unittest import mock

from app.sync import runner, service


class _Config:
    """Cấu hình tối thiểu, đúng những trường `SyncService` đọc."""

    def __init__(self, **kwargs):
        self.hub_url = kwargs.get("hub_url", "https://hub.test")
        self.hub_batch_size = kwargs.get("hub_batch_size", 50)
        self.cv_folder = kwargs.get("cv_folder", "")
        self.db_path = kwargs.get("db_path", ":memory:")
        self._api_key = kwargs.get("api_key", "khoa-test")
        self.saved = 0

    def hub_api_key(self):
        return self._api_key

    def set_hub_api_key(self, value):
        self._api_key = value

    def save(self):
        self.saved += 1


class _FakeDb:
    def __init__(self, stats=None):
        self._stats = stats or {"pending": 0, "inflight": 0, "synced": 0,
                                "failed": 0, "total": 0}
        self.requeued = 0
        self.meta = {}
        self.closed = False

    def sync_stats(self):
        return dict(self._stats)

    def requeue_failed_sync(self, entity_type=""):
        self.requeued += 1
        return 7

    def recover_sync_queue(self):
        return 0

    def count_parsed_terminal(self):
        return 0

    def get_meta(self, key, default=None):
        return self.meta.get(key, default)

    def set_meta(self, key, value):
        self.meta[key] = value

    def close(self):
        self.closed = True


class _FakeApp:
    """Đóng thế `WebApi`: chỉ những gì `SyncService` thật sự dùng."""

    def __init__(self, config=None, db=None):
        self._cfg = config or _Config()
        self._fake_db = db or _FakeDb()
        self.logs = []
        self.evals = []

    def _db(self):
        return self._fake_db

    def log(self, text, level="INFO", source="system"):
        self.logs.append((level, str(text)))

    def _eval(self, script):
        self.evals.append(script)


class WiringTest(unittest.TestCase):
    """Mã đồng bộ phải nối được vào ứng dụng, không phải nằm đó làm cảnh."""

    def test_web_api_co_du_cau_noi_dong_bo(self):
        """Thiếu bất kỳ phương thức nào ở đây thì giao diện không gọi được.

        Đây là bài canh chống việc mã đồng bộ lại thành mã chết: `app/sync/`
        từng đầy đủ và có test mà không ai gọi, và không bài kiểm đơn vị nào
        phát hiện ra.
        """
        from app.web_api import Api

        for name in ("get_sync_status", "test_hub_connection",
                     "register_edge_with_hub", "sync_now", "retry_failed_sync",
                     "save_hub_config"):
            self.assertTrue(callable(getattr(Api, name, None)),
                            f"WebApi thiếu cầu nối «{name}» — giao diện không gọi được")

    def test_runner_co_ham_quet_toan_bo_tai_lieu(self):
        """Thiếu hàm này thì chỉ 1000 CV mới nhất được đồng bộ, phần còn lại
        không bao giờ tới Hub — và hàng đợi trống nên không ai biết."""
        self.assertTrue(callable(getattr(runner, "scan_all_documents", None)))

    def test_quet_tai_lieu_tra_ve_con_tro_de_phan_trang(self):
        self.assertIn("after_rowid", runner.scan_documents.__code__.co_varnames)


class StatusTest(unittest.TestCase):
    def test_bao_dung_trang_thai_chua_cau_hinh(self):
        app = _FakeApp(_Config(hub_url="", api_key=""))
        status = service.SyncService(app).status()
        self.assertFalse(status["configured"])
        self.assertFalse(status["syncing"])
        self.assertFalse(status["blocked_by_user"])
        self.assertNotIn("auto_running", status)

    def test_CSDL_hong_tra_ban_dem_cu_khong_tra_0(self):
        """Đang tải/parsing độc quyền CSDL: trả bản đếm tốt gần nhất + cờ stale,
        KHÔNG để nhật ký báo '0 CV' dù CV đã đồng bộ."""
        app = _FakeApp()
        sync = service.SyncService(app)
        sync._last_stats = {"pending": 0, "inflight": 0, "synced": 42,
                            "failed": 0, "total": 42}
        sync._open_db = mock.Mock(side_effect=RuntimeError("CSDL đang bận"))
        status = sync.status()
        self.assertTrue(status["configured"])
        self.assertTrue(status["stale"])
        self.assertEqual(status["queue"]["synced"], 42)

    def test_is_syncing_tu_go_khi_qua_han(self):
        """Lượt trước treo (mạng chết) -> quá STALE_RUN_SECONDS thì tự coi là xong."""
        sync = service.SyncService(_FakeApp())
        sync._running = True
        sync._started_at = 1.0    # rất xa trong quá khứ
        self.assertFalse(sync.is_syncing())
        self.assertFalse(sync._running)


class ConnectionTest(unittest.TestCase):
    def test_chua_cau_hinh_thi_bao_ro_rang(self):
        app = _FakeApp(_Config(hub_url="", api_key=""))
        result = service.SyncService(app).test_connection()
        self.assertFalse(result["ok"])
        self.assertIn("Chưa cấu hình", result["error"])

    def test_khoa_bi_tu_choi_bao_dung_nguyen_nhan(self):
        from app.sync.client import HubAuthError

        app = _FakeApp()
        sync = service.SyncService(app)
        with mock.patch.object(sync, "_client") as make:
            make.return_value.health.side_effect = HubAuthError("401")
            result = sync.test_connection()
        self.assertFalse(result["ok"])
        self.assertIn("API key", result["error"])

    def test_ket_noi_tot(self):
        app = _FakeApp()
        sync = service.SyncService(app)
        with mock.patch.object(sync, "_client") as make:
            make.return_value.health.return_value = {"ok": True}
            self.assertTrue(sync.test_connection()["ok"])


class RunOnceTest(unittest.TestCase):
    def setUp(self):
        self.app = _FakeApp()
        self.sync = service.SyncService(self.app)
        # _run_once mở kết nối CSDL riêng; thay bằng fake trong RAM.
        self.sync._open_db = lambda: self.app._fake_db

    def _patch_runner(self, totals=None, drain=None):
        totals = totals or {"claimed": 2, "synced": 2, "retry": 0, "failed": 0,
                            "skipped": 0, "uploaded": 1, "batches": 1, "error": ""}
        return mock.patch.multiple(
            runner,
            scan_candidates=mock.Mock(return_value=(2, 10)),
            scan_documents=mock.Mock(return_value=(1, 5)),
            scan_all_candidates=mock.Mock(return_value=20),
            scan_all_documents=mock.Mock(return_value=15),
            drain=drain or mock.Mock(return_value=totals))

    def test_luot_binh_thuong_ghi_nhan_ket_qua(self):
        with self._patch_runner():
            result = self.sync._run_once(mock.Mock())
        self.assertEqual(result["synced"], 2)
        self.assertEqual(result["queued"], 35)
        self.assertIn("seconds", result)

    def test_quet_toan_bo_va_luot_thuong_cung_khong_bo_sot_sau_1000(self):
        with self._patch_runner():
            result = self.sync._run_once(mock.Mock(), full=True)
        self.assertEqual(result["queued"], 35)     # 20 ứng viên + 15 tài liệu

    def test_LOI_khong_bao_gio_thoat_ra_ngoai(self):
        """Đồng bộ hỏng không được phép làm dừng việc thu thập CV."""
        with self._patch_runner(drain=mock.Mock(side_effect=RuntimeError("mạng sập"))):
            result = self.sync._run_once(mock.Mock())
        self.assertIn("mạng sập", result["error"])
        self.assertTrue(any("ERROR" == level for level, _ in self.app.logs))

    def test_co_ban_ghi_that_bai_thi_chi_duong_sua(self):
        """Báo lỗi không kèm lối thoát chỉ làm người dùng lo mà không làm gì được."""
        totals = {"claimed": 5, "synced": 2, "retry": 0, "failed": 3,
                  "skipped": 0, "uploaded": 0, "batches": 1, "error": ""}
        with self._patch_runner(totals=totals):
            self.sync._run_once(mock.Mock())
        self.assertTrue(any("Thử lại" in text for _level, text in self.app.logs))

    def test_day_trang_thai_sang_giao_dien(self):
        with self._patch_runner():
            self.sync._run_once(mock.Mock())
        self.assertTrue(any("onSyncStatus" in script for script in self.app.evals))


class CircuitBreakerTest(unittest.TestCase):
    """Lỗi liên tiếp -> tạm nghỉ, không đập vào Hub mỗi nhịp điều phối."""

    def setUp(self):
        self.app = _FakeApp()
        self.sync = service.SyncService(self.app)
        self.sync._open_db = lambda: self.app._fake_db

    def _err(self):
        return mock.patch.multiple(
            runner,
            scan_candidates=mock.Mock(return_value=(0, 0)),
            scan_documents=mock.Mock(return_value=(0, 0)),
            drain=mock.Mock(side_effect=RuntimeError("Hub sập")))

    def _ok(self):
        return mock.patch.multiple(
            runner,
            scan_candidates=mock.Mock(return_value=(0, 0)),
            scan_documents=mock.Mock(return_value=(0, 0)),
            drain=mock.Mock(return_value={"claimed": 0, "synced": 0, "retry": 0,
                                          "failed": 0, "skipped": 0, "uploaded": 0,
                                          "batches": 0, "error": ""}))

    def test_loi_bat_dau_khoang_nghi_va_chan_luot_moi(self):
        with self._err():
            self.sync._run_once(mock.Mock())
        self.assertEqual(self.sync._fail_streak, 1)
        self.assertTrue(self.sync.in_cooldown())
        result = self.sync.run_pass()
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("cooldown"))
        self.assertGreater(self.sync.status()["cooldown_sec"], 0)

    def test_loi_lien_tiep_thi_khoang_nghi_dai_ra(self):
        with self._err():
            self.sync._run_once(mock.Mock())
            first = self.sync._cooldown_until
            self.sync._run_once(mock.Mock())
        self.assertEqual(self.sync._fail_streak, 2)
        self.assertGreater(self.sync._cooldown_until, first)

    def test_luot_khong_loi_go_ngay_khoang_nghi(self):
        with self._err():
            self.sync._run_once(mock.Mock())
        self.assertTrue(self.sync.in_cooldown())
        with self._ok():
            self.sync._run_once(mock.Mock())
        self.assertEqual(self.sync._fail_streak, 0)
        self.assertFalse(self.sync.in_cooldown())


class ClientWiringTest(unittest.TestCase):
    def test_client_nhan_proxy_va_verify_tu_net(self):
        app = _FakeApp()
        sync = service.SyncService(app)
        with mock.patch("app.net.resolve_proxies",
                        return_value={"https": "http://p:8080"}), \
                mock.patch("app.net.verify_for", return_value="C:/ca.pem"):
            client = sync._client()
        self.assertEqual(client._proxies, {"https": "http://p:8080"})
        self.assertEqual(client._verify, "C:/ca.pem")
        self.assertGreaterEqual(client.upload_timeout, client.timeout)


class BatchSizeTest(unittest.TestCase):
    def test_kep_lo_qua_lon(self):
        """Hub từ chối lô lớn bằng 413, và 413 hiện là lỗi vĩnh viễn — người
        dùng sửa cấu hình thành 1000 sẽ tự khoá mình ra khỏi việc đồng bộ."""
        app = _FakeApp(_Config(hub_batch_size=1000))
        self.assertLessEqual(service.SyncService(app)._batch_size(), 200)

    def test_gia_tri_la_khong_lam_no(self):
        app = _FakeApp(_Config(hub_batch_size="rất nhiều"))
        self.assertEqual(service.SyncService(app)._batch_size(), 50)

    def test_gia_tri_hop_le_duoc_giu(self):
        app = _FakeApp(_Config(hub_batch_size=100))
        self.assertEqual(service.SyncService(app)._batch_size(), 100)


class NoTimerTest(unittest.TestCase):
    def test_khong_con_hen_gio(self):
        """Đã bỏ hẳn vòng lặp định kỳ - điều phối tự chạy theo delta."""
        sync = service.SyncService(_FakeApp())
        for gone in ("start_auto", "stop_auto", "is_scheduled"):
            self.assertFalse(hasattr(sync, gone), gone)

    def test_pause_dung_drain_giua_chung(self):
        """pause() đặt cờ để runner.drain dừng gọn sau lô hiện tại."""
        app = _FakeApp()
        sync = service.SyncService(app)
        sync._open_db = lambda: app._fake_db
        sync._running = True
        sync.pause("nhường cho tải")
        captured = {}

        def fake_drain(*a, **kw):
            captured["should_continue"] = kw.get("should_continue")
            return {"claimed": 0, "synced": 0, "retry": 0, "failed": 0,
                    "skipped": 0, "uploaded": 0, "batches": 0, "error": ""}

        with mock.patch.multiple(
                runner,
                scan_candidates=mock.Mock(return_value=(0, 0)),
                scan_documents=mock.Mock(return_value=(0, 0)),
                drain=mock.Mock(side_effect=fake_drain)):
            sync._run_once(mock.Mock())
        self.assertFalse(captured["should_continue"]())

    def test_hwm_ghi_khi_luot_khong_loi(self):
        app = _FakeApp()
        sync = service.SyncService(app)
        sync._open_db = lambda: app._fake_db
        with mock.patch.multiple(
                runner,
                scan_all_candidates=mock.Mock(return_value=0),
                scan_all_documents=mock.Mock(return_value=0),
                drain=mock.Mock(return_value={"claimed": 0, "synced": 0, "retry": 0,
                                              "failed": 0, "skipped": 0, "uploaded": 0,
                                              "batches": 0, "error": ""})):
            sync._run_once(mock.Mock(), full=True, mark_parsed_hwm=123)
        self.assertEqual(app._fake_db.meta.get("sync_hwm_parsed"), "123")


class RetryFailedTest(unittest.TestCase):
    def test_xep_lai_ban_ghi_that_bai(self):
        """Không có nút này thì dữ liệu kẹt vĩnh viễn ở trạng thái failed."""
        app = _FakeApp()
        sync = service.SyncService(app)
        sync._open_db = lambda: app._fake_db
        result = sync.retry_failed()
        self.assertTrue(result["ok"])
        self.assertEqual(result["requeued"], 7)
        self.assertEqual(app._fake_db.requeued, 1)


class ConcurrencyTest(unittest.TestCase):
    def test_khong_chay_hai_luot_cung_luc(self):
        """Hai luồng cùng claim_sync_batch sẽ tranh nhau cùng những hàng đó."""
        sync = service.SyncService(_FakeApp())
        sync._running = True
        result = sync.run_pass()
        self.assertFalse(result["ok"])
        self.assertIn("đang chạy", result["error"])

    def test_run_pass_tra_ngay_khong_cho(self):
        app = _FakeApp()
        sync = service.SyncService(app)
        sync._open_db = lambda: app._fake_db
        done = threading.Event()
        with mock.patch.object(sync, "_run_once", side_effect=lambda *a, **k: done.set()):
            self.assertTrue(sync.run_pass()["ok"])
            self.assertTrue(done.wait(3))


if __name__ == "__main__":
    unittest.main()


class ScreenTest(unittest.TestCase):
    """Màn hình Hub phải tồn tại và gọi đúng cầu nối.

    Cầu nối JS có đủ mà không có màn hình thì người dùng vẫn không bật được
    đồng bộ — đúng tình trạng trước bản này, chỉ khác chỗ đứt.
    """

    @staticmethod
    def _read(name):
        import os

        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "app", "web", name), encoding="utf-8") as handle:
            return handle.read()

    def test_co_tab_va_man_hinh_Hub(self):
        html = self._read("index.html")
        self.assertIn('data-tab="tab-hub"', html)
        self.assertIn('id="tab-hub"', html)

    def test_co_du_o_nhap_ket_noi(self):
        html = self._read("index.html")
        for element in ("hub-url", "hub-api-key", "hub-edge-id"):
            self.assertIn(f'id="{element}"', html, element)

    def test_co_du_nut_thao_tac(self):
        html = self._read("index.html")
        for button in ("btn-hub-sync-now", "btn-hub-sync-full",
                       "btn-hub-retry-failed", "btn-hub-save", "btn-hub-test",
                       "btn-hub-register"):
            self.assertIn(f'id="{button}"', html, button)

    def test_khong_con_o_hen_gio_dong_bo(self):
        """Đồng bộ tự động theo pipeline - không còn ô chu kỳ hay nút bật/tắt."""
        html = self._read("index.html")
        for gone in ('id="hub-interval"', 'id="btn-hub-auto-start"', 'id="btn-hub-auto-stop"'):
            self.assertNotIn(gone, html, gone)

    def test_JS_goi_dung_cau_noi(self):
        """Tên phương thức lệch giữa JS và Python thì nút bấm im lặng không phản hồi."""
        script = self._read("app.js")
        for call in ("get_sync_status", "sync_now", "retry_failed_sync",
                     "save_hub_config", "test_hub_connection",
                     "register_edge_with_hub"):
            self.assertIn(f"api.{call}(", script, call)

    def test_JS_nhan_duoc_trang_thai_may_chu_day_sang(self):
        """`service._push_status()` gọi `window.app.onSyncStatus(...)`."""
        self.assertIn("onSyncStatus(status)", self._read("app.js"))
