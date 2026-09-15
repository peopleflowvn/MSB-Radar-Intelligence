# -*- coding: utf-8 -*-
"""
Thông báo trên Windows (Trung tâm thông báo, góc dưới màn hình) - để người dùng biết
ngay khi hẹn giờ tìm thấy CV mới mà KHÔNG cần mở cửa sổ phần mềm lên xem.

Dùng PowerShell (có sẵn trên mọi máy Windows 10/11) để hiển thị thay vì đóng gói thêm
thư viện phụ vào file .exe - vừa nhẹ vừa tránh các lỗi đóng gói COM/WinRT hay gặp.

Lưu ý: đây là thông báo "cố gắng hết sức" (best-effort). Máy được quản lý bởi công ty
(Group Policy, phần mềm quản trị tập trung...) có thể chặn thông báo từ ứng dụng chưa
đăng ký hoặc chưa ký số. Có nút "Thử Thông Báo Windows" trong phần Hẹn giờ của tab Cấu hình để kiểm tra ngay xem
máy của bạn có hiển thị được hay không.
"""
import os
import subprocess
import threading

# Đọc Title/Message qua biến môi trường thay vì chèn thẳng vào script PowerShell,
# để tránh mọi rắc rối về escape ký tự đặc biệt (", $, `, &, tiếng Việt có dấu...).
_PS_SCRIPT = r"""
$ErrorActionPreference = "SilentlyContinue"
try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null
    function Esc($s) {
        if ($null -eq $s) { return "" }
        return ($s -replace '&','&amp;' -replace '<','&lt;' -replace '>','&gt;')
    }
    $title = Esc($env:MSB_RADAR_TOAST_TITLE)
    $msg   = Esc($env:MSB_RADAR_TOAST_MSG)
    $xml = "<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$msg</text></binding></visual></toast>"
    $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
    $doc.LoadXml($xml)
    $toast = New-Object Windows.UI.Notifications.ToastNotification $doc
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("MSB Radar Edge").Show($toast)
} catch {
    exit 1
}
"""


def notify(title: str, message: str, blocking: bool = False) -> bool:
    """
    Hiện 1 thông báo Windows. Mặc định chạy nền (không chặn luồng gọi).
    Trả về True nếu tiến trình PowerShell chạy xong không lỗi (không đảm bảo người dùng
    thực sự NHÌN THẤY thông báo - Windows có thể im lặng chặn nó tuỳ cấu hình máy).
    """
    def _run():
        try:
            env = os.environ.copy()
            clean_title = str(title or "").strip()
            env["MSB_RADAR_TOAST_TITLE"] = (clean_title if clean_title.startswith("MSB Radar Edge")
                                          else f"MSB Radar Edge — {clean_title}")
            env["MSB_RADAR_TOAST_MSG"] = str(message)
            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", _PS_SCRIPT],
                env=env, timeout=15, capture_output=True, **kwargs,
            )
            return result.returncode == 0
        except Exception:
            return False

    if blocking:
        return _run()
    threading.Thread(target=_run, daemon=True).start()
    return True
