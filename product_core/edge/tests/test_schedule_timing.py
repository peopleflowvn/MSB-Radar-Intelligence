# -*- coding: utf-8 -*-
"""Hẹn giờ tải CV: giờ chạy tiếp theo phải nằm trên một LƯỚI CỐ ĐỊNH
(anchor + k*interval), không tính từ lúc lượt trước kết thúc - tránh trôi giờ
khi một lượt chạy lâu (vd JobsGO quét toàn bộ hồ sơ). Lỗi liên tiếp phải giãn
thêm thời gian nghỉ, không chỉ chạy lại đúng interval_min.

Dùng `Api.__new__(Api)` để gọi các phương thức này mà không phải khởi tạo toàn
bộ `Api` (tkinter, AppConfig.load() từ file thật...) - cùng cách các API khác
trong lớp này đã hỗ trợ sẵn cho unit test (xem docstring `serialized_db_api`).
"""
import unittest
from datetime import datetime, timedelta

from app.web_api import Api, SCHEDULE_MAX_BACKOFF_MINUTES


class GridNextRunTests(unittest.TestCase):
    def test_returns_anchor_when_still_in_future(self):
        anchor = datetime(2026, 1, 1, 8, 0)
        now = datetime(2026, 1, 1, 7, 0)
        self.assertEqual(Api._grid_next_run(anchor, 60, now), anchor)

    def test_advances_by_one_interval_for_a_fast_run(self):
        anchor = datetime(2026, 1, 1, 8, 0)
        now = datetime(2026, 1, 1, 8, 1)          # lượt vừa chạy xong rất nhanh
        self.assertEqual(Api._grid_next_run(anchor, 60, now), datetime(2026, 1, 1, 9, 0))

    def test_does_not_drift_when_a_run_takes_long(self):
        """Mấu chốt chống trôi giờ: lượt 08:00 chạy mất 50 phút (xong lúc 08:50,
        vẫn chưa hết interval 60 phút) - mốc tiếp theo vẫn là 09:00 đúng lưới,
        KHÔNG phải 08:50 + 60' = 09:50 (kiểu tính "now + interval" cũ, gây trôi
        giờ dần qua mỗi lượt chạy lâu)."""
        anchor = datetime(2026, 1, 1, 8, 0)
        now = datetime(2026, 1, 1, 8, 50)
        self.assertEqual(Api._grid_next_run(anchor, 60, now), datetime(2026, 1, 1, 9, 0))

    def test_skips_missed_slots_without_catch_up_spam(self):
        """Nếu lượt trước chạy quá lâu và lỡ mất nhiều nhịp, nhảy thẳng tới
        nhịp gần nhất còn ở tương lai - không chạy bù liên tiếp từng nhịp đã lỡ."""
        anchor = datetime(2026, 1, 1, 8, 0)
        now = datetime(2026, 1, 1, 10, 30)        # lỡ mất nhịp 09:00 và 10:00
        self.assertEqual(Api._grid_next_run(anchor, 60, now), datetime(2026, 1, 1, 11, 0))

    def test_clamps_interval_to_minimum_15_minutes(self):
        anchor = datetime(2026, 1, 1, 8, 0)
        now = datetime(2026, 1, 1, 8, 1)
        self.assertEqual(Api._grid_next_run(anchor, 1, now), datetime(2026, 1, 1, 8, 15))


class NextScheduleRunTests(unittest.TestCase):
    @staticmethod
    def _api():
        api = Api.__new__(Api)
        api._scheduler_job_anchor = {}
        return api

    def test_uses_grid_when_job_has_no_recent_failure(self):
        api = self._api()
        api._scheduler_job_anchor["job1"] = datetime(2026, 1, 1, 8, 0)
        now = datetime(2026, 1, 1, 8, 5)
        job = {"interval_min": 60, "fail_streak": 0}
        self.assertEqual(api._next_schedule_run("job1", job, now=now), datetime(2026, 1, 1, 9, 0))

    def test_adds_backoff_after_consecutive_failures(self):
        """Lịch lỗi liên tiếp (vd sai mật khẩu) phải giãn thêm thời gian nghỉ,
        không chỉ chạy lại đúng interval_min - tránh dội liên tục vào một tài
        khoản/site đang lỗi."""
        api = self._api()
        api._scheduler_job_anchor["job1"] = datetime(2026, 1, 1, 8, 0)
        now = datetime(2026, 1, 1, 8, 5)
        job = {"interval_min": 15, "fail_streak": 3}
        next_at = api._next_schedule_run("job1", job, now=now)
        # Lưới thường sẽ là 08:15 (interval 15'), nhưng lỗi liên tiếp x3 -> nghỉ
        # thêm 15*3 = 45' kể từ hiện tại, xa hơn mốc lưới thường.
        self.assertEqual(next_at, now + timedelta(minutes=45))

    def test_caps_backoff_at_max_configured(self):
        api = self._api()
        api._scheduler_job_anchor["job1"] = datetime(2026, 1, 1, 8, 0)
        now = datetime(2026, 1, 1, 8, 5)
        job = {"interval_min": 60, "fail_streak": 100}
        next_at = api._next_schedule_run("job1", job, now=now)
        self.assertEqual(next_at, now + timedelta(minutes=SCHEDULE_MAX_BACKOFF_MINUTES))

    def test_resets_to_grid_once_a_run_succeeds(self):
        api = self._api()
        api._scheduler_job_anchor["job1"] = datetime(2026, 1, 1, 8, 0)
        now = datetime(2026, 1, 1, 8, 5)
        job = {"interval_min": 60, "fail_streak": 0}   # đã hết lỗi (thành công lần cuối)
        self.assertEqual(api._next_schedule_run("job1", job, now=now), datetime(2026, 1, 1, 9, 0))


if __name__ == "__main__":
    unittest.main()
