import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import patch

from app.db import Database
from app.engine import SyncEngine
from app.web_api import Api


class _AliveThread:
    @staticmethod
    def is_alive():
        return True


class _IdleParsing:
    status = {"total": 41, "done": 17, "pending": 24}

    @staticmethod
    def running():
        return False


def _busy_api():
    api = Api.__new__(Api)
    api._lock = threading.Lock()
    api._engine_thread = _AliveThread()
    api._parsing = _IdleParsing()
    api._cfg = SimpleNamespace(
        db_path=r"G:\My Drive\Data\MSB_Radar_Data\test.db")
    api._data_stats_cache = {"total": 123, "done": 120, "failed": 3}
    api._checkpoint_cache = {"careerviet:careerviet-account": {
        "last_page": 9, "next_page": 10, "total_pages": 20,
        "start_page": 1, "end_page": 20, "reverse": False,
        "has_more": True, "timestamp": "2026-08-14 04:00:00",
    }}
    api._db = lambda: (_ for _ in ()).throw(
        AssertionError("UI must not open SQLite while engine owns cloud DB"))
    return api


def test_busy_ui_stats_and_checkpoint_use_ram_only():
    api = _busy_api()
    stats = api.get_stats()
    checkpoint = api.get_checkpoint("careerviet", "careerviet-account")
    assert stats["total"] == 123 and stats["from_memory"] is True
    assert checkpoint["last_page"] == 9 and checkpoint["busy"] is True


def test_parsing_status_does_not_open_cloud_db_while_download_is_running():
    api = _busy_api()
    api._exclusive_db_owner = True
    with patch.object(Api, "_with_ocr_status", side_effect=lambda stats: stats):
        status = api.get_cv_parsing_status()
    assert status["done"] == 17
    assert status["running"] is False
    assert status["database_busy"] is True


def test_exclusive_owner_rejects_even_an_existing_ui_connection():
    api = Api.__new__(Api)
    api._db_lock = threading.RLock()
    api._cfg = SimpleNamespace(
        db_path=r"G:\My Drive\Data\MSB_Radar_Data\test.db")
    api._db_conn = SimpleNamespace(conn=object())
    api._db_conn_path = api._cfg.db_path
    api._exclusive_db_owner = True
    api._parsing = _IdleParsing()
    try:
        api._db()
    except sqlite3.OperationalError as exc:
        assert "sử dụng độc quyền" in str(exc)
    else:
        raise AssertionError("exclusive engine ownership must block UI connection reuse")


def test_checkpoint_is_written_as_one_batch():
    captured = {}

    class FakeDb:
        def set_meta_many(self, values):
            captured.update(values)

    engine = SyncEngine.__new__(SyncEngine)
    engine.source = "careerviet"
    engine.account = "hr@example.test"
    engine.log = lambda _message: None
    assert engine._save_checkpoint(
        FakeDb(), last_page=9, next_page=10, total_pages=20,
        start_page=1, end_page=20, reverse=False, has_more=True)
    assert len(captured) == 8
    assert any(key.endswith("next_page") and value == 10
               for key, value in captured.items())


def test_cloud_open_and_io_errors_are_retryable():
    cloud = Database(r"G:\My Drive\Data\MSB_Radar_Data\test.db")
    local = Database(r"C:\MSBRadarEdge\test.db")
    error = sqlite3.OperationalError("unable to open database file")
    assert cloud._is_transient_write_error(error)
    assert not local._is_transient_write_error(error)


def test_ui_database_api_waits_for_connection_handoff_lock():
    called = threading.Event()

    class FakeDb:
        def stats(self):
            called.set()
            return {"total": 1, "done": 1, "failed": 0}

    api = Api.__new__(Api)
    api._db_access_lock = threading.RLock()
    api._lock = threading.Lock()
    api._engine_thread = None
    api._parsing = _IdleParsing()
    api._exclusive_db_owner = False
    api._cfg = SimpleNamespace(db_path=r"C:\MSBRadarEdge\test.db")
    api._data_stats_cache = None
    api._db = lambda: FakeDb()

    api._db_access_lock.acquire()
    reader = threading.Thread(target=api.get_stats)
    reader.start()
    try:
        assert not called.wait(0.1), "UI query must not enter while DB ownership is handed off"
    finally:
        api._db_access_lock.release()
    reader.join(timeout=1)
    assert called.is_set() and not reader.is_alive()
