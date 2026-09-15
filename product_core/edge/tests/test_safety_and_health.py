import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.config import AppConfig
from app.db import Database, is_cloud_synced_path
from app.exporter import export_rows
from app.secrets import SecretStore
from app.web_api import Api


class SecretAndConfigSafetyTests(unittest.TestCase):
    def test_provider_account_save_returns_success_and_normalizes_email(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig()
        api._cfg.save = MagicMock()
        api._account_has_password = MagicMock(return_value=False)

        result = api.save_provider_account({
            "source": "topcv", "email": "  HR@Example.Test ",
            "label": "Tuyển dụng", "enabled": True})

        self.assertTrue(result["ok"])
        self.assertEqual(api._cfg.provider_accounts[0]["email"], "hr@example.test")
        api._cfg.save.assert_called_once()

    def test_needs_setup_accepts_enabled_account_with_account_secret(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(provider_accounts=[{
            "id": "acc1", "source": "itviec", "email": "hr@example.test",
            "label": "ITViec", "enabled": True}])
        api._account_has_password = MagicMock(return_value=True)

        self.assertFalse(api.needs_setup())
        api._account_has_password.assert_called_once_with(api._cfg.provider_accounts[0])

    def test_needs_setup_stays_locked_without_enabled_account_secret(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(provider_accounts=[{
            "id": "acc1", "source": "topcv", "email": "hr@example.test",
            "label": "TopCV", "enabled": True}])
        api._account_has_password = MagicMock(return_value=False)

        self.assertTrue(api.needs_setup())

    def test_needs_setup_ignores_disabled_account(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(provider_accounts=[{
            "id": "acc1", "source": "topcv", "email": "hr@example.test",
            "label": "TopCV", "enabled": False}])
        api._account_has_password = MagicMock(return_value=True)

        self.assertTrue(api.needs_setup())
        api._account_has_password.assert_not_called()

    def test_provider_account_save_failure_is_reported_and_rolled_back(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(provider_accounts=[{
            "id": "existing", "source": "topcv", "email": "old@example.test",
            "label": "Cũ", "enabled": True}])
        api._cfg.save = MagicMock(side_effect=OSError("ổ đĩa không ghi được"))

        result = api.save_provider_account({
            "source": "itviec", "email": "new@example.test", "enabled": True})

        self.assertFalse(result["ok"])
        self.assertIn("Không ghi được cấu hình tài khoản", result["error"])
        self.assertEqual([row["id"] for row in api._cfg.provider_accounts], ["existing"])

    def test_provider_account_delete_cleans_secrets_and_legacy_fields(self):
        api = Api.__new__(Api)
        api.is_downloading = MagicMock(return_value=False)
        api._account_secret_key = MagicMock(return_value="account:acc1")
        api._cfg = AppConfig(
            email="hr@example.test",
            provider_accounts=[{
                "id": "acc1", "source": "topcv", "email": "hr@example.test",
                "label": "TopCV", "enabled": True}],
            schedule_jobs=[{"id": "job1", "name": "Lịch", "sources": ["topcv"], "account_ids": ["acc1"]}])
        api._cfg.save = MagicMock()

        with patch("app.secrets.SecretStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store_cls.return_value = mock_store
            result = api.delete_provider_account("acc1")

        self.assertTrue(result["ok"])
        self.assertEqual(api._cfg.provider_accounts, [])
        self.assertEqual(api._cfg.email, "")
        self.assertEqual(api._cfg.schedule_jobs[0]["account_ids"], [])
        api._cfg.save.assert_called_once()
        mock_store.set.assert_any_call("account:acc1", "")
        mock_store.set.assert_any_call("password", "")

    def test_schedule_job_delete_removes_from_config(self):
        api = Api.__new__(Api)
        api._scheduler_job_next = {"job1": None, "job2": None}
        api._scheduler_job_anchor = {"job1": None, "job2": None}
        api._cfg = AppConfig(
            schedule_jobs=[{"id": "job1", "name": "Lịch 1"}, {"id": "job2", "name": "Lịch 2"}])
        api._cfg.save = MagicMock()

        result = api.delete_schedule_job("job1")

        self.assertTrue(result["ok"])
        self.assertEqual([j["id"] for j in api._cfg.schedule_jobs], ["job2"])
        self.assertNotIn("job1", api._scheduler_job_next)
        api._cfg.save.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_secret_store_round_trip_is_encrypted_at_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "secrets.json")
            store = SecretStore(path)
            store.set("itviec_password", "not-plain-secret")
            self.assertEqual(store.get("itviec_password"), "not-plain-secret")
            with open(path, encoding="utf-8") as handle:
                self.assertNotIn("not-plain-secret", handle.read())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_legacy_plaintext_password_is_migrated_out_of_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "cauhinh.json")
            secret_path = os.path.join(tmp, "secrets.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump({"itviec_email": "a@example.test",
                           "itviec_password": "legacy-secret"}, handle)
            with patch("app.config.CONFIG_PATH", config_path), \
                    patch("app.config.SECRET_PATH", secret_path):
                cfg = AppConfig.load()
            self.assertEqual(cfg.itviec_password, "legacy-secret")
            with open(config_path, encoding="utf-8") as handle:
                self.assertNotIn("legacy-secret", handle.read())
            with open(config_path + ".bak", encoding="utf-8") as handle:
                self.assertNotIn("legacy-secret", handle.read())
            self.assertEqual(SecretStore(secret_path).get("itviec_password"), "legacy-secret")

    def test_api_never_returns_passwords_to_frontend(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(password="top-secret", itviec_password="it-secret")
        result = api.get_config()
        self.assertNotIn("password", result)
        self.assertNotIn("itviec_password", result)
        self.assertTrue(result["password_status"]["topcv"])
        self.assertTrue(result["password_status"]["itviec"])


class DatabaseSafetyTests(unittest.TestCase):
    def test_database_write_retries_temporary_lock(self):
        db = Database(":memory:", log=lambda *_: None)
        db.conn = MagicMock()
        db.conn.execute.side_effect = [sqlite3.OperationalError("database is locked"), object()]
        with patch("app.db.time.sleep"):
            result = db._write("UPDATE meta SET value=?", ("x",), "test")
        self.assertIsNotNone(result)
        self.assertEqual(db.conn.execute.call_count, 2)

    def test_cloud_database_paths_use_safe_journal_detection(self):
        self.assertTrue(is_cloud_synced_path(r"G:\My Drive\Data\database.db"))
        self.assertTrue(is_cloud_synced_path(r"C:\Users\A\OneDrive\database.db"))
        self.assertFalse(is_cloud_synced_path(r"C:\MSBRadar\database.db"))

    def test_cloud_database_uses_delete_journal(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("app.db.is_cloud_synced_path", return_value=True):
            db = Database(os.path.join(tmp, "cloud.db"), log=lambda *_: None).open()
            try:
                mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "delete")
                self.assertEqual(db.conn.execute("PRAGMA mmap_size").fetchone()[0], 0)
            finally:
                db.close()

    def test_account_normalization_migration_is_not_rewritten_on_every_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "accounts.db"), log=lambda *_: None).open()
            try:
                db.upsert({"source": "topcv", "account": "hr@example.test",
                           "cv_id": "1", "fullname": "Candidate"})
                before = db.conn.total_changes
                Database._migrate_account_key(db.conn, db.path)
                self.assertEqual(db.conn.total_changes, before)
                self.assertEqual(db.get_meta("account_normalization_version"), "1")
            finally:
                db.close()

    def test_legacy_migration_creates_backup_and_health_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "legacy.db")
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE candidates (
                    source TEXT NOT NULL, cv_id TEXT NOT NULL, account TEXT,
                    fullname TEXT, email TEXT, phone TEXT, position TEXT,
                    applied_ts TEXT, dl_status TEXT, PRIMARY KEY (source, cv_id));
                INSERT INTO candidates(source,cv_id,account,fullname)
                VALUES ('itviec','1','a@example.test','A');
            """)
            conn.close()
            db = Database(path, log=lambda *_: None).open()
            try:
                self.assertTrue(os.path.isfile(path + ".pre-schema-v2.bak"))
                health = db.health()
                self.assertEqual(health["quick_check"], "ok")
                self.assertEqual(health["schema_version"], Database.SCHEMA_VERSION)
                self.assertEqual(health["rows"], 1)
            finally:
                db.close()

    def test_delete_requires_scope_and_confirmation(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig()
        api._engine_thread = None
        self.assertFalse(api.delete_candidate_data({}, "XOA DU LIEU")["ok"])
        self.assertFalse(api.delete_candidate_data({"source": "itviec"}, "wrong")["ok"])

    def test_candidate_alerts_include_repeat_positions_and_contact_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "alerts.db"), log=lambda *_: None).open()
            try:
                for cv_id, source, position, applied_at in (
                    ("1", "topcv", "Kế toán", "11/08/2026"),
                    ("2", "vietnamworks", "Nhân sự", "13/08/2026"),
                ):
                    db.upsert({"source": source, "account": "hr@example.test", "cv_id": cv_id,
                               "fullname": "Nguyễn A", "email": "A@Example.Test",
                               "phone": "090-123-4567", "position": position,
                               "applied_at": applied_at, "dl_status": "Đã tải",
                               "filename": cv_id + ".pdf"})
                db.upsert({"source": "itviec", "account": "hr@example.test", "cv_id": "3",
                           "fullname": "Thiếu liên hệ", "dl_status": "Lỗi"})
                db.commit()
                rows = [dict(db.get_candidate("topcv", "1", "hr@example.test")),
                        dict(db.get_candidate("itviec", "3", "hr@example.test"))]
                warnings = db.candidate_alerts(rows)
                repeated = warnings[("topcv", "hr@example.test", "1")]
                missing = warnings[("itviec", "hr@example.test", "3")]
                self.assertEqual(repeated["short"], "🔁 2 lần")
                self.assertIn("Kế toán", repeated["detail"])
                self.assertIn("Nhân sự", repeated["detail"])
                self.assertLess(repeated["detail"].index("1. 13/08/2026"),
                                repeated["detail"].index("2. 11/08/2026"))
                self.assertEqual([item["filename"] for item in repeated["applications"]],
                                 ["2.pdf", "1.pdf"])
                self.assertEqual(repeated["applications"][0]["position"], "Nhân sự")
                self.assertIn("Thiếu cả email", missing["detail"])
            finally:
                db.close()

    def test_quick_search_covers_extended_fields_and_account_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "filters.db"), log=lambda *_: None).open()
            try:
                db.upsert({"source": "topcv", "account": "one@example.test", "cv_id": "1",
                           "fullname": "Nguyễn A", "skills": "Power BI chuyên sâu",
                           "expected_salary": "25 triệu"})
                db.upsert({"source": "itviec", "account": "two@example.test", "cv_id": "2",
                           "fullname": "Nguyễn B", "note": "Ưu tiên phỏng vấn sáng"})
                db.commit()
                rows, total = db.query(search="Power BI", limit=20)
                self.assertEqual(total, 1)
                self.assertEqual(rows[0]["cv_id"], "1")
                rows, total = db.query(search="phỏng vấn sáng", limit=20)
                self.assertEqual(total, 1)
                rows, total = db.query(search="nguyen power", limit=20)
                self.assertEqual(total, 1, "FTS phải tìm không dấu và ghép nhiều từ")
                rows, total = db.query(search="Power OR sáng", limit=20)
                self.assertEqual(total, 2, "Boolean OR phải trả về một trong hai nhánh")
                rows, total = db.query(search="nguyen NOT Power", limit=20)
                self.assertEqual(total, 1)
                self.assertEqual(rows[0]["cv_id"], "2")
                rows, total = db.query(search='"Power BI"', limit=20)
                self.assertEqual(total, 1, "Cụm từ trong ngoặc kép phải giữ đúng thứ tự")
                rows, total = db.query(source=["topcv", "itviec"],
                                       account=["one@example.test", "two@example.test"], limit=20)
                self.assertEqual(total, 2)
                options = db.candidate_filter_accounts()
                self.assertEqual({row["account"] for row in options},
                                 {"one@example.test", "two@example.test"})
            finally:
                db.close()

    def test_filter_breakdown_counts_sources_and_application_years(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "breakdown.db"), log=lambda *_: None).open()
            try:
                for cv_id, source, applied_ts in (
                        ("1", "topcv", "2026-01-02 08:00:00"),
                        ("2", "topcv", "2025-05-01 09:00:00"),
                        ("3", "itviec", "2026-07-01 10:00:00"),
                        ("4", "itviec", "")):
                    db.upsert({"source": source, "account": "hr@example.test",
                               "cv_id": cv_id, "fullname": "Ứng viên", "applied_ts": applied_ts})
                db.commit()
                result = db.candidate_filter_breakdown(account="hr@example.test")
                self.assertEqual({x["value"]: x["count"] for x in result["by_source"]},
                                 {"topcv": 2, "itviec": 2})
                self.assertEqual({x["value"]: x["count"] for x in result["by_year"]},
                                 {"2026": 2, "2025": 1, "Không rõ năm": 1})
            finally:
                db.close()

    def test_report_multi_filters_unique_people_accounts_and_trend_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "report.db"), log=lambda *_: None).open()
            try:
                rows = [
                    {"source": "topcv", "account": "a@example.test", "cv_id": "1",
                     "email": "same@example.test", "phone": "090 111 2222", "position": "Dev",
                     "applied_ts": "2026-01-01 08:00:00"},
                    {"source": "itviec", "account": "b@example.test", "cv_id": "2",
                     "email": "SAME@example.test", "position": "Dev",
                     "applied_ts": "2026-01-01 09:00:00"},
                    {"source": "topcv", "account": "a@example.test", "cv_id": "3",
                     "phone": "090-999-8888", "position": "QA",
                     "applied_ts": "2026-02-01 09:00:00"},
                ]
                for row in rows:
                    db.upsert(row)
                db.commit()
                common = {"source": ["topcv", "itviec"], "position": ["Dev", "QA"]}
                self.assertEqual(db.stats(**common)["total"], 3)
                summary = db.stats_report_summary(**common)
                self.assertEqual(summary["n"], 3)
                self.assertEqual(summary["has_email"], 2)
                self.assertEqual(summary["has_phone"], 2)
                self.assertEqual(summary["invalid_dates"], 0)
                self.assertEqual(db.stats_unique_candidates(**common)["unique"], 2)
                account_rows = db.stats_by_source_account(**common)
                self.assertEqual(sum(item["count"] for item in account_rows), 3)
                self.assertTrue(all("done" in item for item in account_rows))
                trend = db.stats_by_day_source(**common, granularity="month")
                self.assertEqual({(item["date"], item["source"]) for item in trend},
                                 {("2026-01", "topcv"), ("2026-01", "itviec"),
                                  ("2026-02", "topcv")})
            finally:
                db.close()


class CandidateListCacheTests(unittest.TestCase):
    def test_cloud_sync_returns_cached_page_without_opening_database(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(db_path=r"G:\My Drive\Data\candidates.db")
        api._engine_thread = type("Thread", (), {"is_alive": lambda self: True})()
        api._lock = __import__("threading").Lock()
        key = (50, 0, "", "", "", "", "", "", "", "applied_ts", "DESC")
        api._candidate_cache = {key: {"items": [{"fullname": "Cached"}], "total": 1,
                                      "stale": False}}
        api._db = MagicMock(side_effect=AssertionError("must not open cloud DB"))

        result = api.get_candidates({"limit": 50})

        self.assertTrue(result["stale"])
        self.assertEqual(result["items"][0]["fullname"], "Cached")
        api._db.assert_not_called()

    def test_realtime_candidate_updates_cached_first_page_and_breakdowns(self):
        api = Api.__new__(Api)
        api._ui_lock = __import__("threading").Lock()
        api._ui_candidates = []
        key = (50, 0, "", "", "", "", "", "", "", "applied_ts", "DESC")
        api._candidate_cache = {key: {
            "items": [], "total": 10, "stale": False,
            "by_source": [{"value": "topcv", "count": 10}],
            "by_year": [{"value": "2026", "count": 10}],
        }}
        api._on_candidate({
            "source": "itviec", "account": "hr@example.test", "cv_id": "new-1",
            "fullname": "Ứng viên mới", "applied_ts": "2025-08-12 10:00:00",
            "dl_status": "Đã tải", "filename": "new-1.pdf",
        }, True)
        cached = api._candidate_cache[key]
        self.assertEqual(cached["total"], 11)
        self.assertEqual(cached["items"][0]["cv_id"], "new-1")
        self.assertEqual({x["value"]: x["count"] for x in cached["by_source"]},
                         {"topcv": 10, "itviec": 1})
        self.assertEqual({x["value"]: x["count"] for x in cached["by_year"]},
                         {"2026": 10, "2025": 1})
        self.assertEqual(len(api._ui_candidates), 1)

    def test_parser_extensions_are_versioned_outside_core_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "extensions.db"), log=lambda *_: None).open()
            try:
                db.upsert({"source": "topcv", "account": "hr@example.test",
                           "cv_id": "cv-1", "fullname": "Parser Candidate"})
                db.set_extension("topcv", "hr@example.test", "cv-1", "cv_parser",
                                 {"languages": ["vi", "en"], "score": 0.92}, 2)
                data = db.get_extensions("topcv", "hr@example.test", "cv-1")
                self.assertEqual(data["cv_parser"]["schema_version"], 2)
                self.assertEqual(data["cv_parser"]["payload"]["score"], 0.92)
            finally:
                db.close()

    def test_large_query_is_consumed_in_bounded_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "stream.db"), log=lambda *_: None).open()
            try:
                for index in range(250):
                    db.upsert({"source": "topcv", "account": "hr@example.test",
                               "cv_id": str(index), "fullname": f"Candidate {index}"})
                sizes = [len(batch) for batch in db.iter_query(
                    batch_size=100, columns=["source", "account", "cv_id", "fullname"])]
                self.assertEqual(sizes, [100, 100, 50])
            finally:
                db.close()

    def test_csv_export_accepts_streaming_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "stream.csv")
            rows = ({"source": "topcv", "account": "a", "cv_id": str(index)}
                    for index in range(25))
            self.assertEqual(export_rows(rows, path, "csv"), 25)
            self.assertGreater(os.path.getsize(path), 0)

    def test_candidate_detail_reads_fresh_row_even_while_downloading(self):
        """Modal "Xem chi tiết" đọc lẻ một dòng từ CSDL: các trường chỉ có sau
        khi mở trang chi tiết (nơi làm việc mong muốn, tình trạng hôn nhân...)
        phải trả về đúng kể cả khi bảng danh sách đang là snapshot RAM cũ."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "detail.db"), log=lambda *_: None).open()
            try:
                db.upsert({"source": "vietnamworks", "account": "hr@example.test",
                           "cv_id": "63291377", "fullname": "Lê Anh Sơn Bùi",
                           "desired_location": "Hà Nội", "marital_status": "Maried",
                           "foreign_language": "German - Native", "detail_loaded": 1})
                # db_path kiểu cloud + coi như đang tải: get_candidate_detail vẫn
                # phải đọc tươi (nó không chặn theo cờ downloading/parsing).
                api = Api.__new__(Api)
                api._cfg = AppConfig(db_path=r"G:\My Drive\Data\detail.db")
                api._engine_thread = type("T", (), {"is_alive": lambda self: True})()
                api._parsing = type("P", (), {"running": lambda self: True})()
                api._db = lambda: db

                res = api.get_candidate_detail("vietnamworks", "hr@example.test", "63291377")

                self.assertTrue(res["ok"])
                self.assertEqual(res["candidate"]["desired_location"], "Hà Nội")
                self.assertEqual(res["candidate"]["marital_status"], "Maried")
                self.assertEqual(res["candidate"]["foreign_language"], "German - Native")

                missing = api.get_candidate_detail("vietnamworks", "hr@example.test", "nope")
                self.assertFalse(missing["ok"])
            finally:
                db.close()

    def test_export_includes_new_desired_fields_and_handles_missing_keys(self):
        """Xuất CSV/XLSX bám EXPORT_COLUMNS nên các cột mới (nơi làm việc mong
        muốn...) tự có; dòng thiếu key vẫn xuất được (giá trị rỗng)."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                {"source": "vietnamworks", "account": "a", "cv_id": "1",
                 "fullname": "A", "desired_location": "Hà Nội",
                 "marital_status": "Đã kết hôn", "dl_status": ""},
                {"source": "itviec", "account": "a", "cv_id": "2", "dl_status": ""},
            ]
            csv_path = os.path.join(tmp, "x.csv")
            export_rows(list(rows), csv_path, "csv")
            head = open(csv_path, encoding="utf-8-sig").read()
            self.assertIn("Nơi làm việc mong muốn", head)
            self.assertIn("Tình trạng hôn nhân", head)
            self.assertIn("Hà Nội", head)

            xlsx_path = os.path.join(tmp, "x.xlsx")
            self.assertEqual(export_rows(list(rows), xlsx_path, "xlsx"), 2)
            self.assertGreater(os.path.getsize(xlsx_path), 0)


class ReportCacheTests(unittest.TestCase):
    def test_downloading_returns_immediately_without_database_query(self):
        api = Api.__new__(Api)
        api._engine_thread = type("Thread", (), {"is_alive": lambda self: True})()
        api._lock = __import__("threading").Lock()
        api._report_cache = {}
        api._data_stats_cache = {"total": 60944, "done": 60000, "failed": 944}
        api._db = MagicMock(side_effect=AssertionError("must not aggregate while downloading"))

        result = api.get_report({"source": [], "time_range": "all"})

        self.assertTrue(result["busy"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["total"], 60944)
        self.assertEqual(result["done"], 60000)
        self.assertEqual(result["failed"], 944)
        api._db.assert_not_called()

    def test_downloading_returns_matching_cached_report(self):
        api = Api.__new__(Api)
        api._engine_thread = type("Thread", (), {"is_alive": lambda self: True})()
        api._lock = __import__("threading").Lock()
        filters = {"source": ["topcv"], "time_range": "all"}
        key = __import__("json").dumps(filters, sort_keys=True, ensure_ascii=False)
        api._report_cache = {key: {"total": 12}}

        result = api.get_report(filters)

        self.assertTrue(result["stale"])
        self.assertEqual(result["total"], 12)


class SmartScheduleTests(unittest.TestCase):
    def _api(self):
        api = Api.__new__(Api)
        api._cfg = AppConfig(provider_accounts=[
            {"id": "a1", "source": "topcv", "email": "a@example.test", "enabled": True},
            {"id": "a2", "source": "itviec", "email": "b@example.test", "enabled": True},
        ])
        api._cfg.save = MagicMock()
        api._scheduler_thread = None
        api._scheduler_stop = __import__("threading").Event()
        api._scheduler_next_run = None
        api._scheduler_job_next = {}
        api._scheduler_job_anchor = {}
        return api

    def test_schedule_requires_name_and_available_account(self):
        api = self._api()
        self.assertFalse(api.save_schedule_job({
            "name": "", "sources": ["topcv"], "mode": "moi"})["ok"])
        result = api.save_schedule_job({
            "name": "CV mới", "sources": ["topcv"], "account_ids": ["a1"],
            "mode": "moi", "interval_min": 1, "enabled": True})
        self.assertTrue(result["ok"])
        self.assertEqual(result["job"]["interval_min"], 15)

    def test_status_reports_each_job_scope_and_overlap(self):
        api = self._api()
        api._cfg.schedule_jobs = [
            {"id": "j1", "name": "Một", "sources": ["topcv"], "account_ids": [],
             "mode": "moi", "interval_min": 60, "enabled": True},
            {"id": "j2", "name": "Hai", "sources": ["topcv"], "account_ids": ["a1"],
             "mode": "moi", "interval_min": 60, "enabled": True},
        ]
        status = api.get_schedule_status()
        self.assertEqual(status["enabled_count"], 2)
        self.assertEqual(status["jobs"][0]["account_count"], 1)
        self.assertTrue(any("trùng phạm vi" in issue for issue in status["jobs"][1]["issues"]))


if __name__ == "__main__":
    unittest.main()
