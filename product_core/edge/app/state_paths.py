# -*- coding: utf-8 -*-
"""Nguồn sự thật duy nhất về nơi MSB Radar Edge lưu state cục bộ trên máy.

State cục bộ gồm: kho bí mật DPAPI (secrets.json), các profile Chrome của từng
tài khoản provider, tessdata OCR tải thêm, catalog job VietnamWorks. Đây KHÔNG
phải dữ liệu ứng viên — dữ liệu ứng viên nằm cạnh chương trình theo cấu hình.

MSB Radar Edge kế thừa từ GenSync Radar nên state cũ nằm ở %LOCALAPPDATA%\\GenSyncRadar.
Module này chuyển sang %LOCALAPPDATA%\\MSBRadar đúng MỘT lần, để dự án tách hẳn
khỏi GenSync Radar mà người dùng không phải đăng nhập lại 5 cổng tuyển dụng
(mỗi lần đăng nhập lại là một lần phải qua CAPTCHA thủ công).

Hai hàm, hai vai trò tách bạch — đừng gộp lại:

  local_state_dir()       Thuần giải quyết đường dẫn, KHÔNG chạm đĩa. An toàn để
                          gọi lúc import module, kể cả trong test.
  migrate_legacy_state()  Thực sự di chuyển thư mục. Chỉ được gọi tường minh từ
                          main.py lúc khởi động, không bao giờ là side effect của
                          import — nếu không, chỉ cần chạy pytest là đã dời mất
                          profile Chrome thật của người dùng.
"""
import os

# Tên thư mục state của MSB Radar Edge.
APP_STATE_FOLDER = "MSBRadar"

# Các tên cũ cần chuyển sang, xếp theo thứ tự ưu tiên. Thêm tên mới vào đầu danh
# sách nếu sau này còn đổi thương hiệu lần nữa.
LEGACY_STATE_FOLDERS = ("GenSyncRadar",)

# Đặt biến môi trường này = "off" để bỏ qua di chuyển (ví dụ khi muốn chạy song
# song GenSync Radar bản cũ trong giai đoạn chuyển tiếp).
MIGRATION_ENV = "MSB_RADAR_STATE_MIGRATION"

_POINTER_NAME = "DA_CHUYEN_SANG_MSB_RADAR.txt"

_cached_dir = None


def _base_dir() -> str:
    """Thư mục cha chứa state. Không import app.config để tránh vòng lặp import."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return base
    # Máy dev/test không có LOCALAPPDATA: lùi về thư mục chương trình, giống
    # nhánh không-đóng-gói của config.app_dir().
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def target_state_dir(base=None) -> str:
    """Đường dẫn state ĐÍCH của MSB Radar Edge, bất kể đã di chuyển hay chưa."""
    return os.path.join(base or _base_dir(), APP_STATE_FOLDER)


def legacy_state_dirs(base=None) -> list:
    """Các đường dẫn state cũ có thể còn tồn tại trên máy."""
    root = base or _base_dir()
    return [os.path.join(root, name) for name in LEGACY_STATE_FOLDERS]


def resolve_state_dir(base=None) -> str:
    """Trả về thư mục state đang có hiệu lực, KHÔNG tạo và KHÔNG di chuyển gì.

    Ưu tiên thư mục mới. Nếu chưa có mà vẫn còn thư mục cũ thì dùng thư mục cũ,
    để ứng dụng vẫn chạy đúng trong phiên mà việc di chuyển chưa thành công
    (ví dụ Chrome đang giữ file trong profile).
    """
    target = target_state_dir(base)
    if os.path.isdir(target):
        return target
    for legacy in legacy_state_dirs(base):
        if os.path.isdir(legacy):
            return legacy
    return target


def local_state_dir() -> str:
    """resolve_state_dir() có nhớ kết quả, dùng cho toàn bộ ứng dụng."""
    global _cached_dir
    if _cached_dir is None:
        _cached_dir = resolve_state_dir()
    return _cached_dir


def reset_cache() -> None:
    """Xoá kết quả đã nhớ. Gọi sau khi di chuyển, và trong test."""
    global _cached_dir
    _cached_dir = None


def _write_pointer(legacy_dir, target_dir) -> None:
    """Để lại ghi chú ở chỗ cũ, tránh người sau mở ra thấy trống rồi hoang mang."""
    try:
        os.makedirs(legacy_dir, exist_ok=True)
        with open(os.path.join(legacy_dir, _POINTER_NAME), "w", encoding="utf-8-sig") as handle:
            handle.write(
                "Toàn bộ state cục bộ của GenSync Radar đã được chuyển sang MSB Radar Edge.\n\n"
                f"Vị trí mới: {target_dir}\n\n"
                "Bao gồm: kho mật khẩu DPAPI (secrets.json), profile Chrome của từng tài khoản\n"
                "provider, tessdata OCR và catalog job VietnamWorks.\n\n"
                "Có thể xoá thư mục này. Nếu vẫn cần chạy GenSync Radar bản cũ, hãy đặt biến\n"
                f"môi trường {MIGRATION_ENV}=off rồi chép state ngược trở lại.\n")
    except OSError:
        pass


def migrate_legacy_state(base=None):
    """Chuyển state cũ sang tên mới đúng một lần. Trả về đường dẫn mới nếu có di chuyển.

    Dùng os.rename: hai thư mục luôn cùng một ổ đĩa nên thao tác này tức thì và
    nguyên tử — không có trạng thái chuyển dở dang, và không nhân đôi vài trăm MB
    profile Chrome như khi copy.

    Mọi thất bại đều được nuốt: không có lý do gì để ứng dụng không khởi động
    được chỉ vì đổi tên thư mục không xong. Lần khởi động sau sẽ thử lại.
    """
    if str(os.environ.get(MIGRATION_ENV, "")).strip().lower() == "off":
        return None

    target = target_state_dir(base)
    if os.path.isdir(target):
        return None                      # đã chuyển ở lần chạy trước

    for legacy in legacy_state_dirs(base):
        if not os.path.isdir(legacy):
            continue
        try:
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            os.rename(legacy, target)
        except OSError:
            # Chrome hoặc GenSync Radar bản cũ đang giữ file bên trong. Giữ
            # nguyên hiện trạng và tiếp tục dùng thư mục cũ trong phiên này.
            continue
        _write_pointer(legacy, target)
        reset_cache()
        return target

    return None
