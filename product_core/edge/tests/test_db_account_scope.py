import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from app.config import AppConfig, account_for_source
from app.db import Database, DONE


class DatabaseAccountScopeTests(unittest.TestCase):
    def test_same_source_and_cv_id_are_independent_between_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "account-scope.db"), log=lambda *_: None).open()
            try:
                db.upsert({"source": "itviec", "account": "A@Example.Test",
                           "cv_id": "same-id", "fullname": "Account A", "dl_status": DONE})
                db.upsert({"source": "itviec", "account": "b@example.test",
                           "cv_id": "same-id", "fullname": "Account B", "dl_status": "Lỗi"})
                db.commit()

                self.assertEqual(db.count("itviec"), 2)
                self.assertEqual(db.count("itviec", account="a@example.test"), 1)
                self.assertEqual(db.done_ids("itviec", "a@example.test"), {"same-id"})
                self.assertEqual(db.done_ids("itviec", "b@example.test"), set())
                self.assertEqual(
                    db.get_candidate("itviec", "same-id", "a@example.test")["fullname"],
                    "Account A")
                self.assertEqual(
                    db.get_candidate("itviec", "same-id", "b@example.test")["fullname"],
                    "Account B")
            finally:
                db.close()

    def test_old_source_cv_primary_key_is_migrated_without_data_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "legacy.db")
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE candidates (
                    source TEXT NOT NULL, cv_id TEXT NOT NULL, account TEXT,
                    fullname TEXT, email TEXT, phone TEXT, position TEXT,
                    applied_ts TEXT, dl_status TEXT,
                    PRIMARY KEY (source, cv_id)
                );
                INSERT INTO candidates(source,cv_id,account,fullname,dl_status)
                VALUES ('topcv','legacy-1','OLD@EXAMPLE.TEST','Legacy', 'Đã tải');
            """)
            conn.close()

            db = Database(path, log=lambda *_: None).open()
            try:
                self.assertTrue(os.path.isfile(path + ".pre-schema-v2.bak"))
                pk = [row[1] for row in sorted(
                    db.conn.execute("PRAGMA table_info(candidates)"), key=lambda row: row[5]) if row[5]]
                self.assertEqual(pk, ["source", "account", "cv_id"])
                row = db.get_candidate("topcv", "legacy-1", "old@example.test")
                self.assertEqual(row["fullname"], "Legacy")
            finally:
                db.close()

    def test_every_provider_uses_its_own_configured_account(self):
        cfg = SimpleNamespace(
            email="top@example.test", vietnamworks_email="vw@example.test",
            careerviet_email="cv@example.test", vieclam24h_email="vl@example.test",
            itviec_email="it@example.test")
        self.assertEqual(account_for_source(cfg, "topcv"), "top@example.test")
        self.assertEqual(account_for_source(cfg, "vietnamworks"), "vw@example.test")
        self.assertEqual(account_for_source(cfg, "careerviet"), "cv@example.test")
        self.assertEqual(account_for_source(cfg, "vieclam24h"), "vl@example.test")
        self.assertEqual(account_for_source(cfg, "itviec"), "it@example.test")

    def test_query_selected_returns_only_exact_composite_identities(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "selected.db"), log=lambda *_: None).open()
            try:
                for account, name in (("a@example.test", "A"), ("b@example.test", "B")):
                    db.upsert({"source": "itviec", "account": account, "cv_id": "same-id",
                               "fullname": name, "dl_status": DONE})
                db.commit()
                rows = db.query_selected([
                    {"source": "itviec", "account": "B@EXAMPLE.TEST", "cv_id": "same-id"},
                    {"source": "itviec", "account": "B@EXAMPLE.TEST", "cv_id": "same-id"},
                    {"source": "itviec", "account": "a@example.test", "cv_id": "missing"},
                ])
                self.assertEqual([row["fullname"] for row in rows], ["B"])
            finally:
                db.close()

    def test_chrome_profiles_are_isolated_by_account_without_exposing_email(self):
        first = AppConfig(email="first@example.test", itviec_email="first@example.test")
        second = AppConfig(email="second@example.test", itviec_email="second@example.test")
        self.assertNotEqual(first.profile_dir(), second.profile_dir())
        self.assertNotEqual(first.itviec_profile_dir(), second.itviec_profile_dir())
        self.assertNotIn("first@example.test", first.itviec_profile_dir())

    def test_multiple_accounts_get_independent_runtime_profiles(self):
        cfg = AppConfig(provider_accounts=[
            {"id": "a", "source": "topcv", "email": "a@example.test", "enabled": True},
            {"id": "b", "source": "topcv", "email": "b@example.test", "enabled": True},
            {"id": "off", "source": "topcv", "email": "off@example.test", "enabled": False},
        ])
        accounts = cfg.accounts_for_source("topcv")
        self.assertEqual([row["id"] for row in accounts], ["a", "b"])
        first, second = (cfg.for_account(row) for row in accounts)
        self.assertEqual(first.email, "a@example.test")
        self.assertNotEqual(first.profile_dir(), second.profile_dir())
        self.assertNotIn("a@example.test", first.profile_dir())


if __name__ == "__main__":
    unittest.main()
