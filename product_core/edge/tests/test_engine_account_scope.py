import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.db import Database, DONE
from app.engine import SyncEngine
from app.providers.base import Provider


class FakeProvider(Provider):
    key = "itviec"
    display_name = "ITViec"
    available = True

    def __init__(self, cfg, items):
        super().__init__(cfg, log=lambda *_: None)
        self.items = items
        self.last_page = 1

    def connect(self):
        pass

    def total_count(self):
        return len(self.items)

    def peek_first_page(self):
        return list(self.items)

    def iter_pages(self, start_page=1, end_page=None, reverse=False):
        yield 1, list(self.items)

    def download(self, item_or_id):
        return b"%PDF-1.7\ntest", ".pdf"


class RecoveringProvider(FakeProvider):
    def __init__(self, cfg, items):
        super().__init__(cfg, items)
        self.download_calls = 0
        self.refreshed_ids = []

    def download(self, item_or_id):
        self.download_calls += 1
        if not item_or_id.get("fresh_url"):
            return None, "link hết hạn"
        return b"%PDF-1.7\nrecovered", ".pdf"

    def refresh_failed_item(self, item):
        self.refreshed_ids.append(item["cv_id"])
        item["fresh_url"] = True
        return True


class EngineAccountScopeTests(unittest.TestCase):
    def test_smaller_new_account_is_not_skipped_by_larger_old_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "candidates.db")
            cv_folder = os.path.join(tmp, "cv")
            db = Database(db_path, log=lambda *_: None).open()
            for index in range(5):
                db.upsert({"source": "itviec", "account": "old@example.test",
                           "cv_id": f"old-{index}", "fullname": "Old", "dl_status": DONE})
            db.commit()
            db.close()

            cfg = SimpleNamespace(
                itviec_email="new@example.test", itviec_password="secret",
                cv_folder=cv_folder, db_path=db_path, filename_pattern="{id}_{ten}",
                concurrency=1, delay_ms=0, page_delay_ms=0,
                retry_failed=True, skip_existing_file=True,
                validate=lambda _source: [],
            )
            items = [
                {"source": "itviec", "account": "new@example.test",
                 "cv_id": f"new-{index}", "fullname": f"New {index}"}
                for index in range(2)
            ]
            provider = FakeProvider(cfg, items)
            with patch("app.engine.get_provider", return_value=provider):
                result = SyncEngine(cfg, source="itviec", log=lambda *_: None).run(mode="moi")

            self.assertTrue(result["ok"])
            self.assertEqual(result["new"], 2)
            db = Database(db_path, log=lambda *_: None).open()
            try:
                self.assertEqual(db.count("itviec", account="old@example.test"), 5)
                self.assertEqual(db.count("itviec", account="new@example.test"), 2)
                queued = db.conn.execute(
                    "SELECT COUNT(*) FROM candidate_documents").fetchone()[0]
                self.assertEqual(queued, 0, "Luồng tải không được tự xếp hàng parsing")
            finally:
                db.close()

    def test_retry_failed_refreshes_only_failed_identity_then_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "candidates.db")
            cv_folder = os.path.join(tmp, "cv")
            db = Database(db_path, log=lambda *_: None).open()
            db.upsert({"source": "itviec", "account": "a@example.test",
                       "cv_id": "failed-1", "fullname": "Failed", "dl_status": "Lỗi: link hết hạn"})
            db.upsert({"source": "itviec", "account": "a@example.test",
                       "cv_id": "done-1", "fullname": "Done", "dl_status": DONE})
            db.commit()
            db.close()
            cfg = SimpleNamespace(
                itviec_email="a@example.test", itviec_password="secret",
                cv_folder=cv_folder, db_path=db_path, filename_pattern="{id}_{ten}",
                concurrency=1, delay_ms=0, page_delay_ms=0, retry_failed=True,
                skip_existing_file=True, validate=lambda _source: [],
            )
            provider = RecoveringProvider(cfg, [])
            with patch("app.engine.get_provider", return_value=provider):
                result = SyncEngine(cfg, source="itviec", log=lambda *_: None).run(mode="loi")

            self.assertTrue(result["ok"])
            self.assertEqual(provider.refreshed_ids, ["failed-1"])
            self.assertEqual(provider.download_calls, 2)
            db = Database(db_path, log=lambda *_: None).open()
            try:
                self.assertTrue(db.is_done("itviec", "failed-1", "a@example.test"))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
