# -*- coding: utf-8 -*-
"""
Khoá CẢNH BÁO khi nhiều máy cùng trỏ vào một cơ sở dữ liệu (thường qua Google Drive đồng
bộ) - để tránh 2 máy cùng bấm tải lúc gần nhau, có thể gây xung đột đăng nhập TopCV hoặc
làm hỏng file cơ sở dữ liệu.

Đây là khoá "cố gắng hết sức" (best-effort), KHÔNG phải khoá phân tán chuẩn: Google Drive
đồng bộ file có độ trễ (vài giây tới vài phút), nên vẫn có khả năng (hiếm) 2 máy bấm chạy
gần như cùng lúc mà chưa kịp thấy khoá của nhau. Mục đích chính là chặn trường hợp phổ biến
hơn nhiều: quên tắt hẹn giờ ở máy này rồi bật lên ở máy khác dùng chung dữ liệu.
"""
import json
import os
import socket
import time
from datetime import datetime

STALE_SEC = 5 * 60   # khoá cũ hơn 5 phút coi như máy kia đã dừng/gặp sự cố -> bỏ qua


def _lock_path(db_path):
    return os.path.splitext(db_path)[0] + ".khoa.json"


def check(db_path):
    """Trả về dict thông tin máy khác đang giữ khoá (còn hiệu lực), hoặc None nếu an toàn."""
    path = _lock_path(db_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if data.get("host") == socket.gethostname():
        return None
    age = time.time() - float(data.get("ts", 0))
    if age > STALE_SEC:
        return None
    data["ago_sec"] = age
    return data


def acquire(db_path):
    """Ghi/khởi tạo khoá cho máy này. Gọi lại định kỳ trong lúc chạy để giữ khoá còn hiệu lực."""
    path = _lock_path(db_path)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "host": socket.gethostname(),
                "ts": time.time(),
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }, f)
    except Exception:
        pass


def release(db_path):
    """Giải phóng khoá khi chạy xong - chỉ xoá nếu đúng là khoá của máy này."""
    path = _lock_path(db_path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("host") == socket.gethostname():
            os.remove(path)
    except Exception:
        pass
