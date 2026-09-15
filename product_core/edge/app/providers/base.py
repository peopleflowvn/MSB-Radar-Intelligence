# -*- coding: utf-8 -*-
"""
Giao diện chung cho mọi nguồn tuyển dụng (TopCV, VietnamWorks, ITviec, CareerViet...).

Muốn thêm một nguồn mới:
  1. Tạo file mới trong thư mục này, viết một lớp kế thừa Provider.
  2. Cài đặt 3 việc: connect() / iter_pages() / download().
  3. Khai báo lớp đó trong providers/__init__.py
Phần còn lại (tải song song, chống trùng, ghi cơ sở dữ liệu, giao diện, hẹn giờ)
dùng lại được ngay, không phải sửa gì thêm.
"""
from abc import ABC, abstractmethod
import random


def jitter_delay(seconds, ratio=0.25, random_fn=None):
    """Return a bounded randomized delay used to smooth request load."""
    base = max(0.0, float(seconds or 0.0))
    spread = min(0.80, max(0.0, float(ratio or 0.0)))
    if not base or not spread:
        return base
    picker = random_fn or random.uniform
    return base * picker(1.0 - spread, 1.0 + spread)


class Provider(ABC):
    # Central policy inherited by current and future providers. Explicit
    # Retry-After/server backoff remains separate and takes priority.
    request_jitter_ratio = 0.25
    item_jitter_ratio = 0.30
    page_jitter_ratio = 0.20
    key = ""              # mã nội bộ, vd "topcv"
    display_name = ""     # tên hiển thị, vd "TopCV"
    website = ""
    available = False     # False = chưa hỗ trợ, giao diện sẽ hiện "Đang phát triển"
    note = ""             # ghi chú hiển thị khi chưa hỗ trợ

    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log

    def jitter_delay(self, seconds, ratio=None):
        if ratio is None:
            ratio = self.request_jitter_ratio
        return jitter_delay(seconds, ratio)

    # ---- vòng đời ----
    @abstractmethod
    def connect(self):
        """Đăng nhập / chuẩn bị phiên làm việc. Ném LoginError nếu thất bại."""

    def close(self):
        """Dọn dẹp tài nguyên (đóng trình duyệt...)."""

    # ---- dữ liệu ----
    @abstractmethod
    def total_count(self) -> int:
        """Tổng số lượt ứng tuyển hiện có trên nguồn này (đúng số "Tìm thấy X ứng viên")."""

    def peek_first_page(self):
        """
        Trả về danh sách (đã chuẩn hoá) của TRANG ĐẦU TIÊN mà không tốn thêm lượt gọi
        mạng nào - vì connect() đã phải tải trang đầu để lấy total_count() rồi.
        Dùng để kiểm tra nhanh "có gì mới không" trước khi quyết định quét toàn bộ.
        Mặc định trả về rỗng; các provider có cache trang đầu nên ghi đè hàm này.
        """
        return []

    @abstractmethod
    def iter_pages(self, start_page=1, end_page=None, reverse=False):
        """
        Sinh ra từng trang danh sách, mỗi trang là list các dict đã chuẩn hoá
        theo đúng tên cột trong app/db.py (source, cv_id, fullname, email, ...).
        """

    @abstractmethod
    def download(self, item_or_id):
        """
        Tải file CV.
        Trả về (dữ_liệu_bytes, '.pdf') nếu thành công,
        hoặc (None, 'mô tả lỗi') nếu thất bại.
        """

    def refresh_failed_item(self, item):
        """Refresh exactly one failed application before a second download attempt.

        Providers with a detail API should override this method. Returning True means
        the item was refreshed and the engine should retry; False means there is no
        safe targeted recovery route, so the engine must not scan the whole history.
        """
        return False


class LoginError(Exception):
    """Đăng nhập thất bại - thông báo được hiển thị trực tiếp cho người dùng."""


class NotImplementedProvider(Provider):
    """Nguồn chưa được hỗ trợ - chỉ để hiển thị trên giao diện."""
    available = False

    def connect(self):
        raise LoginError(f"{self.display_name} chưa được hỗ trợ trong phiên bản này.")

    def total_count(self):
        return 0

    def iter_pages(self):
        return iter(())

    def download(self, cv_id):
        return None, "Chưa hỗ trợ"
