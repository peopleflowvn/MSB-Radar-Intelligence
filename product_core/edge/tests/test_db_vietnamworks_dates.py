import os
import tempfile
import unittest

from app.db import Database


class VietnamWorksDateMigrationTests(unittest.TestCase):
    def test_existing_iso_display_date_is_migrated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "candidates.db")
            db = Database(path, log=lambda message: None).open()
            db.upsert({
                "source": "vietnamworks", "cv_id": "63214267",
                "applied_at": "2026-07-31T10:55:08.000Z",
                "applied_ts": "2026-07-31 17:55:08",
            })
            db.commit()
            db.close()

            db = Database(path, log=lambda message: None).open()
            row = db.get_candidate("vietnamworks", "63214267")
            self.assertEqual(row["applied_at"], "31/07/2026 17:55")
            self.assertEqual(row["applied_ts"], "2026-07-31 17:55:08")
            db.close()


if __name__ == "__main__":
    unittest.main()
