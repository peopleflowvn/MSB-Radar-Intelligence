# -*- coding: utf-8 -*-
"""Kiểm thử worker nền.

Điều quan trọng nhất cần khẳng định: worker KHÔNG được tự bật trong lúc chạy
test hay lệnh quản trị. Một luồng nền gọi AI thật trong `manage.py migrate` là
kiểu hỏng vừa tốn tiền vừa khó lần ra.
"""
import sys
from unittest.mock import patch

from django.test import TestCase, override_settings

from . import worker


class CoNenChayWorkerTest(TestCase):
    @override_settings(HUB_BACKGROUND_WORKER=True)
    def test_khong_chay_khi_dang_chay_test(self):
        with patch.object(sys, "argv", ["manage.py", "test"]):
            self.assertFalse(worker.should_start())

    @override_settings(HUB_BACKGROUND_WORKER=True)
    def test_khong_chay_trong_lenh_quan_tri(self):
        for command in ("migrate", "makemigrations", "shell", "collectstatic",
                        "run_extraction_worker", "parse_missing_cvs", "lenh_moi_nao_do"):
            with patch.object(sys, "argv", ["manage.py", command]):
                self.assertFalse(worker.should_start(), command)

    @override_settings(HUB_BACKGROUND_WORKER=True)
    def test_khong_chay_trong_script_python_c(self):
        """Script tay có `django.setup()` là chuyện thường (kể cả script kiểm
        thử của chính mình). Danh sách CHẶN sẽ để chúng lọt qua và âm thầm bật
        một luồng gọi AI — nên phải dùng danh sách CHO PHÉP."""
        with patch.object(sys, "argv", ["-c"]):
            self.assertFalse(worker.should_start())
        with patch.object(sys, "argv", ["kiem_tra_tay.py"]):
            self.assertFalse(worker.should_start())

    @override_settings(HUB_BACKGROUND_WORKER=True)
    def test_runserver_chi_chay_o_tien_trinh_con_cua_autoreload(self):
        """`runserver` sinh hai tiến trình; chạy worker ở cả hai là gọi AI hai lần."""
        with patch.object(sys, "argv", ["manage.py", "runserver"]):
            with patch.dict("os.environ", {}, clear=False) as environ:
                environ.pop("RUN_MAIN", None)
                self.assertFalse(worker.should_start())
            with patch.dict("os.environ", {"RUN_MAIN": "true"}):
                self.assertTrue(worker.should_start())

    @override_settings(HUB_BACKGROUND_WORKER=False)
    def test_tat_bang_cau_hinh(self):
        with patch.object(sys, "argv", ["gunicorn"]):
            self.assertFalse(worker.should_start())

    @override_settings(HUB_BACKGROUND_WORKER=True)
    def test_chay_duoi_may_chu_wsgi_asgi(self):
        for program in ("gunicorn", "/usr/local/bin/gunicorn", "uvicorn", "daphne"):
            with patch.object(sys, "argv", [program, "config.wsgi"]):
                self.assertTrue(worker.should_start(), program)


class VongLapWorkerTest(TestCase):
    def test_mot_buoc_loi_khong_lam_chet_worker_va_khong_chan_buoc_con_lai(self):
        goi = []

        def hong():
            goi.append("hong")
            raise RuntimeError("CSDL bận")

        def chay():
            goi.append("chay")
            worker._stop.set()          # dừng sau đúng một vòng
            return 0

        with patch.object(worker, "_STEPS", (("hỏng", hong), ("chạy", chay))):
            worker._stop.clear()
            with self.assertLogs("core.worker", level="ERROR"):
                worker._loop()
        self.assertEqual(goi, ["hong", "chay"])
