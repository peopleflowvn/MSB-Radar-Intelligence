# -*- coding: utf-8 -*-
"""PipelineCoordinator: tự chạy parsing/đồng bộ theo delta và cho các tầng
nhường máy lẫn nhau theo thứ tự ưu tiên Tải > Parsing > Đồng bộ."""
import unittest

from app.coordinator import PipelineCoordinator


class _Parsing:
    def __init__(self, running=False, allowed=True):
        self._running = running
        self._allowed = allowed
        self.started = None
        self.paused = None

    def running(self):
        return self._running

    def resume_allowed(self):
        return self._allowed

    @property
    def _blocked_by_user(self):
        return not self._allowed

    def pause(self, reason="x"):
        self.paused = reason

    def start(self, backfill=False, skip_failed=False, **kw):
        self.started = {"backfill": backfill, "skip_failed": skip_failed}
        return True


class _Sync:
    def __init__(self, syncing=False, blocked=False, cooldown=False):
        self._syncing = syncing
        self._blocked_by_user = blocked
        self._cooldown = cooldown
        self.passes = []
        self.paused = None
        self.resumed = False

    def is_syncing(self):
        return self._syncing

    def in_cooldown(self):
        return self._cooldown

    def pause(self, reason="x"):
        self.paused = reason

    def resume(self):
        self.resumed = True

    def run_pass(self, full=False, mark_parsed_hwm=None):
        self.passes.append({"full": full, "mark_parsed_hwm": mark_parsed_hwm})
        return {"ok": True}


class _Db:
    def __init__(self, backlog=0, retry=0, pending=0, inflight=0, parsed=0, hwm=0):
        self._backlog = backlog
        self._retry = retry
        self._stats = {"pending": pending, "inflight": inflight}
        self._parsed = parsed
        self.meta = {"sync_hwm_parsed": hwm}

    def requeue_stale_failed_documents(self, *a):
        return self._retry

    def parsing_backlog(self, *a):
        return self._backlog

    def sync_stats(self):
        return dict(self._stats)

    def count_parsed_terminal(self):
        return self._parsed

    def get_meta(self, key, default=None):
        return self.meta.get(key, default)


class _Cfg:
    hub_url = "https://hub.test"

    def hub_api_key(self):
        return "k"


class _App:
    def __init__(self, downloading=False, parsing=None, sync=None, db=None, cfg=None):
        self._downloading = downloading
        self._parsing = parsing or _Parsing()
        self._sync = sync or _Sync()
        self._fake_db = db or _Db()
        self._cfg = cfg or _Cfg()
        self.logs = []
        self.closed_db = False

    def is_downloading(self):
        return self._downloading

    def _db(self):
        return self._fake_db

    def _close_db(self):
        self.closed_db = True

    def log(self, *a, **k):
        self.logs.append(a[0] if a else "")


class PriorityTest(unittest.TestCase):
    def test_dang_tai_thi_khong_khoi_dong_gi(self):
        app = _App(downloading=True, db=_Db(backlog=99, pending=99))
        PipelineCoordinator(app)._tick()
        self.assertIsNone(app._parsing.started)
        self.assertEqual(app._sync.passes, [])

    def test_parsing_dang_chay_thi_dong_bo_nhuong(self):
        app = _App(parsing=_Parsing(running=True))
        PipelineCoordinator(app)._tick()
        self.assertIsNotNone(app._sync.paused)
        self.assertEqual(app._sync.passes, [])

    def test_parsing_uu_tien_hon_dong_bo(self):
        app = _App(db=_Db(backlog=5, pending=10))
        PipelineCoordinator(app)._tick()
        self.assertEqual(app._parsing.started,
                         {"backfill": True, "skip_failed": True})
        self.assertTrue(app.closed_db)
        self.assertEqual(app._sync.passes, [])            # đồng bộ chưa tới lượt


class DeltaTriggerTest(unittest.TestCase):
    def test_khong_ton_dong_parsing_thi_khong_chay(self):
        app = _App(db=_Db(backlog=0, retry=0, pending=0, parsed=0, hwm=0))
        PipelineCoordinator(app)._tick()
        self.assertIsNone(app._parsing.started)
        self.assertEqual(app._sync.passes, [])

    def test_hang_doi_dong_bo_con_ton_thi_drain(self):
        app = _App(db=_Db(backlog=0, pending=3))
        PipelineCoordinator(app)._tick()
        self.assertEqual(app._sync.passes, [{"full": False, "mark_parsed_hwm": None}])

    def test_co_cv_parse_moi_thi_quet_toan_bo_mot_lan(self):
        app = _App(db=_Db(backlog=0, pending=0, parsed=40, hwm=25))
        PipelineCoordinator(app)._tick()
        self.assertEqual(app._sync.passes, [{"full": True, "mark_parsed_hwm": 40}])

    def test_parse_khong_tang_thi_khong_quet_lai(self):
        app = _App(db=_Db(backlog=0, pending=0, parsed=25, hwm=25))
        PipelineCoordinator(app)._tick()
        self.assertEqual(app._sync.passes, [])

    def test_nguoi_dung_tat_parsing_thi_dieu_phoi_khong_tu_chay(self):
        app = _App(parsing=_Parsing(allowed=False), db=_Db(backlog=9))
        PipelineCoordinator(app)._tick()
        self.assertIsNone(app._parsing.started)

    def test_chua_cau_hinh_hub_thi_khong_dong_bo(self):
        class _NoHub(_Cfg):
            hub_url = ""
        app = _App(db=_Db(pending=5), cfg=_NoHub())
        PipelineCoordinator(app)._tick()
        self.assertEqual(app._sync.passes, [])

    def test_hub_dang_nghi_sau_loi_thi_dieu_phoi_khong_goi(self):
        app = _App(sync=_Sync(cooldown=True), db=_Db(pending=9))
        PipelineCoordinator(app)._tick()
        self.assertEqual(app._sync.passes, [])


class DownloadHookTest(unittest.TestCase):
    def test_notify_download_starting_tam_dung_hai_tang_duoi(self):
        app = _App(parsing=_Parsing(running=True), sync=_Sync(syncing=True))
        PipelineCoordinator(app).notify_download_starting()
        self.assertIsNotNone(app._parsing.paused)
        self.assertIsNotNone(app._sync.paused)


if __name__ == "__main__":
    unittest.main()
