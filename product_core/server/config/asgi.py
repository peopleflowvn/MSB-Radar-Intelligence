# -*- coding: utf-8 -*-
"""Điểm vào ASGI.

Chọn ASGI (Master Plan §3.2, phương án A) vì cơ chế Thinking stream token theo
SSE: mỗi kết nối stream giữ một luồng suốt nhiều giây, sync worker của WSGI sẽ
cạn chỗ chỉ với vài người dùng đồng thời.

Production chạy:

    gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker

Các view đồng bộ hiện có không đổi hành vi — Django tự bọc chúng trong luồng.
Chỉ endpoint stream mới viết theo async.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
