# -*- coding: utf-8 -*-
"""Danh tính của bản cài Edge này.

Hub cần biết mỗi bản ghi đến từ Edge nào: để quy trách nhiệm nguồn dữ liệu, để
hiển thị trạng thái từng Edge, và để hai Edge cùng thu thập một tài khoản không
ghi đè kết quả của nhau.

edge_id nằm trong thư mục state cục bộ (%LOCALAPPDATA%\\MSBRadar), KHÔNG nằm
trong cauhinh.json cạnh chương trình. Hệ quả cố ý: chép cả thư mục ứng dụng sang
máy khác sẽ sinh edge_id mới — đúng vì đó là một Edge khác. Nếu để trong
cauhinh.json thì hai máy sẽ cùng khai một danh tính và Hub không phân biệt được.
"""
import json
import os
import platform
import uuid

from ..state_paths import local_state_dir

IDENTITY_FILE = "edge_identity.json"

_cached = None


def _identity_path():
    return os.path.join(local_state_dir(), IDENTITY_FILE)


def edge_identity(refresh=False):
    """Đọc (hoặc tạo lần đầu) danh tính Edge. Trả dict, không bao giờ ném lỗi.

    Không đọc/ghi được đĩa thì vẫn trả về một danh tính dùng trong bộ nhớ, để
    ứng dụng chạy tiếp — mất khả năng đồng bộ không được phép làm hỏng việc thu
    thập CV, vốn là chức năng cốt lõi.
    """
    global _cached
    if _cached is not None and not refresh:
        return _cached

    path = _identity_path()
    data = {}
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict) and loaded.get("edge_id"):
            data = loaded
    except (OSError, ValueError):
        data = {}

    if not data.get("edge_id"):
        data = {
            "edge_id": uuid.uuid4().hex,
            "hostname": platform.node() or "",
            "created_at": _now(),
        }
        _write_identity(path, data)

    # Tên máy có thể đổi sau khi cấp phát; cập nhật để Hub hiển thị đúng, nhưng
    # edge_id thì không bao giờ đổi.
    hostname = platform.node() or ""
    if hostname and data.get("hostname") != hostname:
        data["hostname"] = hostname
        _write_identity(path, data)

    _cached = data
    return data


def edge_id():
    """Định danh ổn định của bản cài Edge này."""
    return edge_identity()["edge_id"]


def reset_cache():
    """Xoá danh tính đã nhớ. Dùng trong test."""
    global _cached
    _cached = None


def _now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_identity(path, data):
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        pass
