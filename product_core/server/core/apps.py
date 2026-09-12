# -*- coding: utf-8 -*-
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Lõi MSB Radar Hub"

    def ready(self):
        # Đăng ký cách mô tả xác thực Edge cho drf-spectacular. Phải import ở
        # đây (không phải ở đầu module khác) vì extension chỉ được nhận diện
        # nếu đã nạp TRƯỚC lúc sinh schema, và `ready()` là điểm Django đảm bảo
        # chạy đúng một lần sau khi mọi app đã nạp xong.
        from . import schema  # noqa: F401

        # Worker nền: chỗ AI thật sự chạy trên dữ liệu mới. Trước đây ba việc
        # nặng (phân giải, parsing bù, bóc fact) chỉ có lệnh gõ tay và không
        # cron nào gọi — đo được 0 fact `source_kind=ai` trên CSDL thật.
        from . import worker
        if worker.should_start():
            worker.start()
