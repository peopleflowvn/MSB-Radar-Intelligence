import unittest
from datetime import datetime

from app.providers.vietnamworks import VietnamWorksProvider


class VietnamWorksHistoryTests(unittest.TestCase):
    def test_created_timestamp_supports_epoch_ms_and_iso(self):
        expected = datetime(2026, 1, 2).timestamp()
        self.assertEqual(
            VietnamWorksProvider._job_created_ts(str(expected * 1000)), expected)
        self.assertEqual(
            VietnamWorksProvider._job_created_ts("2026-01-02T00:00:00"), expected)

    def test_candidate_date_matches_topcv_display_format(self):
        self.assertEqual(
            VietnamWorksProvider._display_timestamp("2026-08-10T07:32:47.000Z"),
            "10/08/2026 14:32")

    def test_full_history_stops_after_30_consecutive_invalid_jobs(self):
        provider = object.__new__(VietnamWorksProvider)
        provider.run_mode = "tatca"
        provider._last_page = 35
        provider._first_page_items = []
        provider._invalid_job_ids = {"0"}  # connect() already prefetched the first task.
        provider._tasks = [
            ({"id": str(index), "title": f"Job {index}",
              "createdDate": str((2_000_000_000 - index) * 1000)}, 1)
            for index in range(35)
        ]
        calls = []
        saved = []
        provider.log = lambda message: None

        def fetch(task):
            calls.append(task[0]["id"])
            provider._invalid_job_ids.add(task[0]["id"])
            return []

        provider._fetch_task = fetch
        provider._save_history_cutoff = saved.append

        yielded = list(provider.iter_pages())

        self.assertEqual(len(calls), 29)  # Page 1 was prefetched by connect().
        self.assertEqual(len(yielded), 29)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0], VietnamWorksProvider._job_created_ts(provider._tasks[0][0]))

    def test_discovery_discards_polluted_virtual_job_cache(self):
        provider = object.__new__(VietnamWorksProvider)
        provider.run_mode = "moi"
        provider.log = lambda message: None
        provider._load_catalog = lambda: {
            "jobs": {"bad": {"id": "bad", "job_status": "virtualJob",
                               "totalApplication": 99}},
            "expired_complete": True,
        }
        requested_types = []

        def scan(status, *args, **kwargs):
            requested_types.append(status)
            return [], 0, True

        provider._scan_job_type = scan
        saved = []
        provider._save_catalog = saved.append

        self.assertEqual(provider._discover_jobs([]), [])
        self.assertIn("virtual-job", requested_types)
        self.assertNotIn("virtualJob", requested_types)
        self.assertNotIn("bad", saved[0]["jobs"])


if __name__ == "__main__":
    unittest.main()
