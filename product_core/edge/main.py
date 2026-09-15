# -*- coding: utf-8 -*-
"""Điểm khởi động chương trình MSB Radar Edge (CV Hub) - PyWebView Edition."""
import sys
import os
import traceback
import faulthandler
import threading
import time
from datetime import datetime

from app.config import app_dir
from app.version import APP_DISPLAY_NAME


from pathlib import Path


MIN_DOTNET_RELEASE = 461808  # .NET Framework 4.7.2 trên Windows 10
_fault_stream = None


def _startup_log(message):
    """Ghi checkpoint tối thiểu; vẫn còn dữ liệu khi CLR/WebView2 crash native."""
    global _fault_stream
    try:
        if _fault_stream is None:
            path = os.path.join(app_dir(), "loi_khoi_dong.log")
            # BOM giúp Notepad/PowerShell cũ nhận đúng tiếng Việt thay vì mojibake.
            _fault_stream = open(path, "w", encoding="utf-8-sig", buffering=1)
            faulthandler.enable(file=_fault_stream, all_threads=True)
        _fault_stream.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")
        _fault_stream.flush()
    except Exception:
        pass


def _show_error(title, message):
    """Hiện lỗi trước khi pywebview/.NET sẵn sàng, không phụ thuộc Tk hay CLR."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return
        except Exception:
            pass
    print(message)


def _dotnet_release():
    if os.name != "nt":
        return MIN_DOTNET_RELEASE
    try:
        import winreg
        path = r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"
        views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
        for view in views:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                                    winreg.KEY_READ | view) as key:
                    return int(winreg.QueryValueEx(key, "Release")[0])
            except OSError:
                continue
    except Exception:
        pass
    return 0


def prepare_windows_runtime():
    """Chỉ kiểm tra .NET; pywebview phải tự nạp CLR trong AppDomain mặc định."""
    if os.name != "nt":
        return
    if _dotnet_release() < MIN_DOTNET_RELEASE:
        raise RuntimeError(
            "Máy tính chưa có Microsoft .NET Framework 4.7.2 trở lên.\n\n"
            "Hãy nhờ IT cài Microsoft .NET Framework 4.8 Runtime, sau đó mở lại "
            "MSB Radar Edge. Không cần cài Python.\n\n"
            "Trang tải chính thức: https://dotnet.microsoft.com/download/dotnet-framework/net48")

def get_web_index_path() -> str:
    """Xác định đường dẫn file:// chuẩn tới index.html (hoạt động cả dev lẫn .exe đóng gói)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", app_dir())
        path = os.path.join(base, "app", "web", "index.html")
        if os.path.exists(path):
            return Path(path).as_uri()
        return Path(os.path.join(base, "web", "index.html")).as_uri()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "web", "index.html")
    return Path(path).as_uri()


def migrate_local_state():
    """Chuyển state cục bộ từ tên GenSync Radar sang MSB Radar, đúng một lần.

    Phải chạy TRƯỚC khi bất kỳ thành phần nào đọc kho bí mật hay mở profile
    Chrome, nếu không phiên này sẽ dùng đường dẫn cũ còn phiên sau dùng đường
    dẫn mới. Cố ý không đặt trong app/config.py: nếu để việc di chuyển thư mục
    xảy ra như side effect của import thì chỉ cần chạy pytest là đã dời mất
    profile Chrome thật của người dùng.
    """
    from app.state_paths import migrate_legacy_state
    from app import config
    moved = migrate_legacy_state()
    if moved:
        config.refresh_state_paths()
        _startup_log(f"Đã chuyển state cục bộ sang {moved}")
    return moved


def main():
    _startup_log("Bắt đầu khởi động")
    migrate_local_state()
    prepare_windows_runtime()
    _startup_log("Đã kiểm tra .NET Framework")
    from app.prerequisites import configure_webview2
    webview2_folder = configure_webview2()
    _startup_log(f"Đã chuẩn bị WebView2: {webview2_folder or 'runtime hệ thống'}")
    import webview
    if webview2_folder:
        # Đây là cơ chế chính thức của pywebview/CoreWebView2CreationProperties.
        # Không ép WebView2Loader bằng biến môi trường toàn tiến trình.
        webview.settings["WEBVIEW2_RUNTIME_PATH"] = webview2_folder
    _startup_log("Đã nạp pywebview/CLR")

    # Trì hoãn import API nặng cho tới khi CLR đã được pywebview khởi tạo đúng cách.
    from app.web_api import Api

    api = Api()
    _startup_log("Đã khởi tạo API và cơ sở dữ liệu")
    html_path = get_web_index_path()

    window = webview.create_window(
        title=APP_DISPLAY_NAME,
        url=html_path,
        js_api=api,
        width=1280,
        height=820,
        min_size=(1024, 700),
        maximized=True,
        background_color="#040B16"
    )
    api.set_window(window)
    _startup_log("Bắt đầu vòng lặp WinForms/WebView2")

    def packaged_startup_probe():
        """Đợi JS bridge xác nhận toàn bộ startup, ghi marker rồi đóng cửa sổ probe sạch sẽ."""
        if os.environ.get("MSB_RADAR_PACKAGED_STARTUP_PROBE") != "1":
            return
        try:
            if not window.events.loaded.wait(30):
                _startup_log("Startup probe: window.events.loaded timed out")
                return
            marker = os.environ.get("MSB_RADAR_PACKAGED_STARTUP_MARKER", "")
            if marker:
                try:
                    with open(marker, "w", encoding="utf-8") as f:
                        f.write("OK")
                except Exception:
                    pass
            time.sleep(1.0)
            window.destroy()
        except Exception:
            _startup_log("Startup probe thất bại:\n" + traceback.format_exc())

    probe = threading.Thread(target=packaged_startup_probe, daemon=True)
    probe.start()
    webview.start(debug=False, gui="edgechromium")
    # Dừng vòng lặp đồng bộ tự động. Luồng là daemon nên tiến trình vẫn thoát
    # được nếu bỏ qua, nhưng dừng tường minh tránh một lượt gửi dở dang ghi
    # thêm vào CSDL sau khi cửa sổ đã đóng.
    try:
        api._coordinator.shutdown()
    except Exception:
        pass
    try:
        api._sync.shutdown()
    except Exception:
        pass
    _startup_log("Ứng dụng đóng bình thường")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        try:
            base = app_dir()
            with open(os.path.join(base, "loi_khoi_dong.log"), "w", encoding="utf-8") as f:
                f.write(err)
        except Exception:
            pass
        detail = str(sys.exc_info()[1] or "")
        if "Python.Runtime.Loader.Initialize" in err:
            message = (
                "Không khởi tạo được thành phần giao diện .NET.\n\n"
                "Hãy bấm chuột phải file ZIP > Properties > chọn Unblock (nếu có), "
                "giải nén lại toàn bộ; đồng thời bảo đảm máy đã có .NET Framework 4.8.\n\n"
                "Chi tiết đã lưu trong loi_khoi_dong.log.")
        else:
            message = detail or "MSB Radar Edge không thể khởi động."
        _show_error(APP_DISPLAY_NAME, message)
        print(err)
        sys.exit(1)
