# -*- coding: utf-8 -*-
"""Lưu trữ file (CV, ảnh đại diện, tài liệu đính kèm).

Hai backend, chọn bằng cấu hình — cùng nguyên tắc với lớp LLM provider: không
khoá nghiệp vụ vào một nhà cung cấp.

    local   Ổ đĩa của VPS Oracle. Mặc định. Không cần tài khoản, không phí ra
            mạng, không thêm một dịch vụ nữa có thể hỏng giữa buổi demo.
    r2      Cloudflare R2 (Master Plan mục 44). Bật khi cần dự phòng nhiều bản
            sao hoặc phục vụ file mà không tốn băng thông VPS.

Vì sao mặc định là local: Oracle Always Free cấp 200 GB block storage. Kho CV
hiện tại khoảng 20 nghìn hồ sơ; với cỡ trung bình 200 KB thì chỉ ~4 GB. Local
thoải mái, và đổi sang R2 sau chỉ là đổi biến môi trường cộng một lần chép dữ liệu.

Đánh đổi phải biết rõ:
    local   một ổ đĩa duy nhất, không tự nhân bản. Sao lưu là việc của bạn.
            VPS hỏng là mất file (metadata trong PostgreSQL vẫn còn).
    r2      có nhân bản, không phí ra mạng, nhưng thêm một bộ khoá phải quản lý.
"""
import hashlib
import os
import shutil

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# Cây thư mục theo 2 tầng đầu của mã băm: 20 nghìn file trong MỘT thư mục làm
# `ls` và mọi thao tác thư mục chậm thấy rõ trên ext4. Chia 256 nhánh giữ mỗi
# nhánh vài trăm file.
FANOUT = 2


class StorageError(RuntimeError):
    pass


def content_key(sha256, filename=""):
    """Khoá lưu trữ suy ra từ nội dung, không phải từ tên file.

    Đặt tên theo nội dung nghĩa là cùng một CV tải về từ TopCV và VietnamWorks
    chỉ chiếm một chỗ. Tên file gốc vẫn nằm trong metadata ở PostgreSQL.
    """
    digest = str(sha256 or "").lower()
    if len(digest) != 64:
        raise StorageError(f"sha256 không hợp lệ: {sha256!r}")
    extension = os.path.splitext(str(filename or ""))[1].lower()[:10]
    return f"{digest[:FANOUT]}/{digest[FANOUT:4]}/{digest}{extension}"


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


class LocalStorage:
    """Lưu trên ổ đĩa VPS."""

    name = "local"

    def __init__(self, root):
        self.root = os.path.abspath(str(root))

    def _path(self, key):
        # Chốt chặn duyệt thư mục: khoá đến từ dữ liệu, nên '../' phải bị chặn
        # trước khi chạm tới hệ thống file (chuẩn hoá cả / và \ trên mọi HĐH).
        normalized_key = str(key or "").replace("\\", "/")
        target = os.path.abspath(os.path.join(self.root, *[part for part in normalized_key.split("/") if part]))
        if not target.startswith(self.root + os.sep):
            raise StorageError(f"Khoá lưu trữ không hợp lệ: {key!r}")
        return target

    def save(self, key, data):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Ghi ra file tạm rồi đổi tên: tiến trình chết giữa chừng sẽ không để
        # lại một file cụt mà mã băm nói là đầy đủ.
        temporary = path + ".part"
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return key

    def open(self, key):
        try:
            return open(self._path(key), "rb")
        except FileNotFoundError as exc:
            raise StorageError(f"Không có file: {key}") from exc

    def read(self, key):
        with self.open(key) as handle:
            return handle.read()

    def exists(self, key):
        return os.path.isfile(self._path(key))

    def delete(self, key):
        try:
            os.remove(self._path(key))
            return True
        except FileNotFoundError:
            return False

    def size(self, key):
        try:
            return os.path.getsize(self._path(key))
        except FileNotFoundError as exc:
            raise StorageError(f"Không có file: {key}") from exc

    def usage(self):
        """Dung lượng đã dùng và còn trống — để cảnh báo trước khi đầy ổ."""
        total, used, free = shutil.disk_usage(self.root) if os.path.isdir(self.root) else (0, 0, 0)
        stored = sum(os.path.getsize(os.path.join(folder, name))
                     for folder, _dirs, files in os.walk(self.root)
                     for name in files if not name.endswith(".part"))
        return {"backend": self.name, "stored_bytes": stored,
                "disk_total_bytes": total, "disk_free_bytes": free}


class R2Storage:
    """Cloudflare R2 qua API tương thích S3.

    Viết sẵn để việc chuyển sang chỉ là đổi biến môi trường, không phải sửa
    nghiệp vụ — dùng thật lần đầu ở triển khai VPS Oracle Core (dùng chung với
    dịch vụ khác, tránh cộng dồn trách nhiệm sao lưu ổ đĩa cho máy không sở
    hữu riêng).
    """

    name = "r2"

    def __init__(self, bucket, account_id, access_key, secret_key, endpoint=""):
        try:
            import boto3
        except ImportError as exc:
            raise ImproperlyConfigured(
                "Backend r2 cần boto3. Cài: pip install boto3") from exc

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto")

    def save(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return key

    def read(self, key):
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:
            raise StorageError(f"Không đọc được {key}: {exc}") from exc

    def open(self, key):
        import io
        return io.BytesIO(self.read(key))

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)
        return True

    def size(self, key):
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        except Exception as exc:
            raise StorageError(f"Không có file: {key}") from exc

    def usage(self):
        # R2 không trả tổng dung lượng qua API S3; xem trên bảng điều khiển.
        return {"backend": self.name, "stored_bytes": None}


_backend = None


def get_storage():
    """Backend đang cấu hình. Nhớ kết quả giữa các lời gọi."""
    global _backend
    if _backend is None:
        _backend = build_storage()
    return _backend


def build_storage(config=None):
    config = config or getattr(settings, "FILE_STORAGE", {})
    backend = str(config.get("backend") or "local").lower()

    if backend == "local":
        return LocalStorage(config.get("root") or (settings.BASE_DIR / "filestore"))

    if backend == "r2":
        missing = [k for k in ("bucket", "account_id", "access_key", "secret_key")
                   if not config.get(k)]
        if missing:
            raise ImproperlyConfigured(
                f"Backend r2 thiếu cấu hình: {', '.join(missing)}")
        return R2Storage(config["bucket"], config["account_id"],
                         config["access_key"], config["secret_key"],
                         config.get("endpoint", ""))

    raise ImproperlyConfigured(f"Backend lưu trữ không hỗ trợ: {backend!r}")


def reset_storage():
    """Xoá backend đã nhớ. Dùng trong test."""
    global _backend
    _backend = None
