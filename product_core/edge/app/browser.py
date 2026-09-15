# -*- coding: utf-8 -*-
"""Tiện ích trình duyệt dùng chung cho mọi nguồn tuyển dụng."""
import os
import queue
import re
import subprocess
import threading
import time


class ChromeStartError(Exception):
    """Không khởi động được Chrome - thông báo tiếng Việt dễ hiểu để hiển thị cho người dùng."""


CHROME_START_TIMEOUT = 150


def open_profile_browser(profile_dir, url):
    """Mở Chrome thường để người dùng tự quản lý phiên của một provider."""
    try:
        import undetected_chromedriver as uc
        chrome = uc.find_chrome_executable()
    except Exception:
        chrome = None
    if not chrome or not os.path.isfile(chrome):
        raise ChromeStartError("Không tìm thấy Google Chrome trên máy.")
    os.makedirs(profile_dir, exist_ok=True)
    try:
        subprocess.Popen([
            chrome,
            f"--user-data-dir={os.path.abspath(profile_dir)}",
            "--no-first-run",
            "--no-default-browser-check",
            str(url),
        ], close_fds=True)
    except Exception as exc:
        raise ChromeStartError(f"Không mở được Chrome profile: {str(exc)[:160]}")
    return True


def profile_browser_processes(profile_dir):
    """Trả PID Chrome đang dùng chính xác profile này."""
    return _profile_chrome_processes(_validated_profile_path(profile_dir))


def close_profile_browser(profile_dir):
    """Đóng Chrome của đúng profile sau khi người dùng đã xác nhận trên UI."""
    profile = _validated_profile_path(profile_dir)
    pids = _profile_chrome_processes(profile)
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"], capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
        except Exception:
            pass
    deadline = time.time() + 5
    while time.time() < deadline and _profile_chrome_processes(profile):
        time.sleep(0.25)
    remaining = _profile_chrome_processes(profile)
    for pid in remaining:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
        except Exception:
            pass
    if _profile_chrome_processes(profile):
        raise ChromeStartError(
            "Không đóng được Chrome profile. Hãy đóng cửa sổ đó bằng tay rồi thử lại.")
    return len(pids)


def _validated_profile_path(profile_dir):
    profile = os.path.normcase(os.path.abspath(str(profile_dir or "")))
    drive_root = os.path.normcase(os.path.abspath(os.path.splitdrive(profile)[0] + os.sep))
    forbidden = {drive_root, os.path.normcase(os.path.abspath(os.path.expanduser("~")))}
    local = os.environ.get("LOCALAPPDATA")
    if local:
        forbidden.add(os.path.normcase(os.path.abspath(local)))
    if not profile or profile in forbidden or len(os.path.basename(profile)) < 4:
        raise ChromeStartError("Đường dẫn Chrome profile không an toàn hoặc không hợp lệ.")
    return profile


def _owned_browser_processes(profile_dir):
    """Return direct Chrome/driver children created by this application process."""
    if os.name != "nt":
        return []
    profile = os.path.normcase(os.path.abspath(profile_dir)).replace("'", "''")
    parent = os.getpid()
    script = (
        f"Get-CimInstance Win32_Process -Filter \"ParentProcessId={parent}\" | "
        "Where-Object { $_.Name -in @('chrome.exe','chromedriver.exe','undetected_chromedriver.exe') "
        f"-and ($_.Name -ne 'chrome.exe' -or $_.CommandLine -like '*{profile}*') }} | "
        "Select-Object -ExpandProperty ProcessId")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
        return [int(value) for value in result.stdout.split() if value.isdigit()]
    except Exception:
        return []


def _cleanup_owned_browser_processes(profile_dir):
    for pid in _owned_browser_processes(profile_dir):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
        except Exception:
            pass


def _profile_chrome_processes(profile_dir):
    """Find Chrome processes using this exact automation profile, including stale apps."""
    if os.name != "nt":
        return []
    profile = os.path.normcase(os.path.abspath(profile_dir)).replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{profile}*' }} | "
        "Select-Object -ExpandProperty ProcessId")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
        return [int(value) for value in result.stdout.split() if value.isdigit()]
    except Exception:
        return []


def _start_with_watchdog(factory, profile_dir, timeout=CHROME_START_TIMEOUT):
    """Do not let uc.Chrome block the download worker forever during handshake."""
    result = queue.Queue(maxsize=1)

    def launch():
        try:
            result.put((True, factory()))
        except BaseException as exc:
            result.put((False, exc))

    worker = threading.Thread(target=launch, name="ChromeStartWatchdog", daemon=True)
    worker.start()
    try:
        ok, value = result.get(timeout=max(0.05, float(timeout)))
    except queue.Empty:
        _cleanup_owned_browser_processes(profile_dir)
        timeout_seconds = max(1, int(float(timeout)))
        raise ChromeStartError(
            f"Chrome đã mở nhưng không kết nối được với phần mềm sau {timeout_seconds} giây. "
            "Các tiến trình Chrome bị treo của lần này đã được đóng an toàn.\n\n"
            "Ở lần chạy đầu, phần mềm có thể cần tải và kiểm tra trình điều khiển Chrome. "
            "Hãy kiểm tra kết nối mạng, đóng cửa sổ Chrome dùng cho MSB Radar Edge nếu còn "
            "hiển thị, rồi bấm tải lại.")
    if not ok:
        raise value
    return value


def detect_chrome_major_version():
    """
    Dò trước phiên bản Chrome THẬT SỰ đang cài trên máy (không phụ thuộc máy nào, phiên
    bản nào) để mở đúng ngay từ lần thử đầu tiên - thay vì luôn thử "bản mới nhất" trước
    rồi mới sửa lại khi sai (cách cũ chậm hơn và luôn báo lỗi-rồi-tự-sửa ở lần chạy đầu
    trên MỌI máy không dùng đúng bản Chrome mới nhất).

    Đọc thông tin phiên bản trực tiếp từ file .exe (qua PowerShell) thay vì chạy
    "chrome.exe --version", vì lệnh đó không đáng tin khi Chrome đang mở sẵn - Chrome sẽ
    chỉ mở thêm tab mới trong cửa sổ đang chạy thay vì in ra phiên bản.

    Trả về số phiên bản chính (vd 150), hoặc None nếu không dò được (khi đó sẽ dùng cách
    dò tự động mặc định của undetected_chromedriver).
    """
    try:
        import undetected_chromedriver as uc
        exe = uc.find_chrome_executable()
        if not exe:
            return None
        import subprocess
        ps_cmd = f"(Get-Item '{exe}').VersionInfo.FileVersion"
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        m = re.search(r"(\d+)", r.stdout.strip())
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _build_options(cfg):
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    # Ngôn ngữ/vùng phải KHỚP với người dùng thật. undetected_chromedriver mặc định ép
    # --lang=en-US; một tài khoản tuyển dụng Việt Nam, mạng Việt Nam mà trình duyệt lại
    # khai báo tiếng Anh-Mỹ là một điểm vênh dễ bị chấm là "bất thường". Khai đúng
    # tiếng Việt cho nhất quán với phần còn lại của phiên làm việc.
    opts.add_argument("--lang=vi-VN,vi")
    opts.add_experimental_option("prefs", {
        "intl.accept_languages": "vi-VN,vi,en-US,en",
        "credentials_enable_service": False,          # tắt hộp thoại "Lưu mật khẩu?" che trang
        "profile.password_manager_enabled": False,
    })

    # Proxy: Chrome tự dùng proxy hệ thống Windows. Chỉ ép cờ khi người dùng nhập
    # proxy_url tường minh trong Cấu hình (vd mạng chỉ khai proxy qua biến môi
    # trường mà Chrome không đọc).
    try:
        from . import net
        proxy_arg = net.chrome_proxy_arg(cfg)
        if proxy_arg:
            opts.add_argument(proxy_arg)
    except Exception:
        pass

    # Không chờ quảng cáo/tracker tải xong -> tránh treo trang
    opts.page_load_strategy = "eager"

    # Chế độ ẩn cửa sổ là một trong những dấu hiệu bị soi kỹ nhất, và quan trọng hơn:
    # nếu TopCV hỏi captcha thì KHÔNG có cửa sổ nào để người dùng xác minh bằng tay.
    # Vì vậy chỉ ẩn khi người dùng chủ động bật trong tab Cấu hình.
    if getattr(cfg, "headless", False):
        opts.add_argument("--headless=new")
    return opts


def start_driver(cfg):
    """Mở Chrome với profile riêng để giữ phiên đăng nhập giữa các lần chạy."""
    import undetected_chromedriver as uc
    from selenium.common.exceptions import SessionNotCreatedException, WebDriverException

    profile_dir = cfg.profile_dir()
    # A previous timed-out launch in the same application may have left direct
    # Chrome/driver children alive and locking this profile.
    _cleanup_owned_browser_processes(profile_dir)
    if _profile_chrome_processes(profile_dir):
        raise ChromeStartError(
            "Profile Chrome của MSB Radar Edge đang được một cửa sổ Chrome khác sử dụng.\n\n"
            "Hãy đóng cửa sổ Chrome VietnamWorks/TopCV còn mở, chờ vài giây rồi bấm tải lại. "
            "Phần mềm không tự đóng cửa sổ thuộc tiến trình khác để tránh làm mất thao tác của người dùng.")
    kwargs = {"options": _build_options(cfg), "user_data_dir": profile_dir}
    configured_version = int(getattr(cfg, "chrome_version", 0) or 0)
    if configured_version > 0:
        kwargs["version_main"] = configured_version
    else:
        detected = detect_chrome_major_version()
        if detected:
            kwargs["version_main"] = detected

    # Đường dẫn chromedriver có sẵn: mạng công ty chặn Google thì undetected-
    # chromedriver không tự tải được driver ở lần chạy đầu. Trỏ vào bản đã có
    # để bỏ qua bước tải.
    driver_path = str(getattr(cfg, "chromedriver_path", "") or "").strip()
    if driver_path and os.path.isfile(driver_path):
        kwargs["driver_executable_path"] = driver_path

    try:
        driver = _start_with_watchdog(lambda: uc.Chrome(**kwargs), profile_dir)
    except SessionNotCreatedException as e:
        # Chrome thường tự cập nhật ngầm (không cần khởi động lại máy) khiến phiên bản
        # trình điều khiển tự dò được bị lệch so với Chrome thực tế đang cài. Thay vì
        # báo lỗi khó hiểu, đọc đúng phiên bản Chrome mà chính Selenium báo về trong
        # thông báo lỗi rồi thử khởi động lại đúng phiên bản đó - tự phục hồi, người
        # dùng thường sẽ không thấy lỗi này chút nào.
        m = re.search(r"[Cc]urrent browser version is (\d+)", str(e))
        if not m:
            raise ChromeStartError(
                "Không khởi động được Chrome.\n\n"
                "Hãy đảm bảo máy đã cài Google Chrome, rồi thử chạy lại. "
                f"(Chi tiết kỹ thuật: {str(e)[:200]})")
        try:
            kwargs["options"] = _build_options(cfg)   # ChromeOptions chỉ dùng được 1 lần
            kwargs["version_main"] = int(m.group(1))
            # Lần thử đầu (dò phiên bản sai) có thể để lại 1 tiến trình chromedriver
            # cũ chạy ngầm, khoá không cho tải lại đúng phiên bản. patcher_force_close
            # buộc tắt tiến trình đó trước khi tải lại - đúng nguyên nhân gây lỗi lặp lại.
            kwargs["patcher_force_close"] = True
            driver = _start_with_watchdog(lambda: uc.Chrome(**kwargs), profile_dir)
        except Exception as e2:
            raise ChromeStartError(
                "Chrome vừa tự cập nhật phiên bản khiến trình điều khiển bị lệch, và "
                "phần mềm thử tự khắc phục nhưng chưa thành công.\n\n"
                "Hãy ĐÓNG HẾT cửa sổ Chrome đang mở rồi chạy lại phần mềm. "
                f"(Chi tiết kỹ thuật: {str(e2)[:200]})")
    except ChromeStartError:
        raise
    except WebDriverException as e:
        raise ChromeStartError(
            "Không khởi động được Chrome.\n\n"
            "Hãy đảm bảo máy đã cài Google Chrome và không có cửa sổ Chrome nào đang treo, "
            f"rồi thử chạy lại. (Chi tiết kỹ thuật: {str(e)[:200]})")
    except Exception as e:
        # Lưới an toàn cuối cùng: bất kỳ lỗi lạ nào khác (thiếu quyền ghi, máy chưa cài
        # Chrome, phần mềm diệt virus chặn...) cũng hiện thông báo tiếng Việt dễ hiểu
        # thay vì để lộ một loạt dòng lỗi kỹ thuật khó hiểu cho người dùng.
        raise ChromeStartError(
            "Không khởi động được Chrome.\n\n"
            "Hãy đảm bảo máy đã cài Google Chrome, có quyền ghi vào thư mục chứa phần mềm, "
            "và không bị phần mềm diệt virus chặn, rồi thử chạy lại. "
            f"(Chi tiết kỹ thuật: {str(e)[:200]})")

    driver.set_page_load_timeout(45)
    # QUAN TRỌNG: chỉ truyền --start-maximized là chưa đủ. Vì dùng profile Chrome
    # cố định (giữ đăng nhập), Chrome sẽ nhớ lại kích thước/vị trí cửa sổ của lần
    # đóng trước đó và ghi đè lên cờ --start-maximized ở lần mở sau. Phải gọi thêm
    # maximize_window() mỗi lần để đảm bảo LUÔN mở toàn màn hình.
    try:
        driver.maximize_window()
    except Exception:
        pass
    return driver


def bring_to_front(driver):
    """Đưa cửa sổ Chrome lên trước mặt người dùng và nháy nút trên thanh taskbar.

    Cần thiết khi TopCV hỏi captcha/OTP: cửa sổ Chrome do phần mềm mở thường nằm SAU
    các cửa sổ đang làm việc, nên người dùng không hề biết là nó đang chờ mình xác minh
    - tưởng phần mềm bị treo. Windows không cho ứng dụng nền tự nhảy lên trên trong mọi
    trường hợp, nên nếu SetForegroundWindow bị từ chối thì nháy nút taskbar để gây chú ý.
    """
    try:
        driver.maximize_window()
    except Exception:
        pass

    pid = getattr(driver, "browser_pid", None)
    if os.name != "nt" or not pid:
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            win_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
            if win_pid.value == pid and user32.GetWindowTextLengthW(hwnd) > 0:
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(_enum, 0)
        if not found:
            return
        hwnd = found[0]
        user32.ShowWindow(hwnd, 9)          # SW_RESTORE (bỏ thu nhỏ nếu đang thu nhỏ)
        if not user32.SetForegroundWindow(hwnd):
            # Bị Windows chặn -> nháy nút trên taskbar cho tới khi người dùng bấm vào
            class FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND),
                            ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
                            ("dwTimeout", wintypes.DWORD)]
            info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x0000000C, 0, 0)
            user32.FlashWindowEx(ctypes.byref(info))   # FLASHW_ALL | FLASHW_TIMERNOFG
    except Exception:
        pass


def safe_get(driver, url, wait=2.0):
    """Mở trang, bỏ qua lỗi hết giờ (trang nặng vẫn dùng được phần đã tải)."""
    from selenium.common.exceptions import TimeoutException
    try:
        driver.get(url)
    except TimeoutException:
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass
    except Exception:
        pass
    time.sleep(wait)


_BROWSER_FETCH_SCRIPT = r"""
    var done = arguments[arguments.length - 1];
    var method = arguments[0], url = arguments[1], bearer = arguments[2];
    var payload = arguments[3], credentials = arguments[4];
    var headers = {"Accept": "application/json, text/plain, application/pdf, */*"};
    if (bearer) headers["Authorization"] = bearer;
    if (payload !== null && payload !== undefined) headers["Content-Type"] = "application/json";
    var finished = false;
    function finish(result) {
        if (finished) return;
        finished = true; clearTimeout(timer); done(result);
    }
    var timer = setTimeout(function () { finish({status: 0, error: "timeout"}); }, 90000);
    fetch(url, {
        method: method, headers: headers, credentials: credentials || "include",
        body: (payload === null || payload === undefined) ? undefined : JSON.stringify(payload)
    }).then(function (response) {
        return response.arrayBuffer().then(function (buffer) {
            var bytes = new Uint8Array(buffer), binary = "", chunk = 8192;
            for (var i = 0; i < bytes.length; i += chunk) {
                binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
            }
            finish({status: response.status, data_b64: btoa(binary)});
        });
    }).catch(function (error) { finish({status: 0, error: String(error)}); });
"""


def browser_fetch_bytes(driver, driver_lock, method, url, *, bearer=None,
                        payload=None, credentials="include"):
    """Gọi `url` NGAY TRONG tab Chrome đã đăng nhập và trả `(status, bytes|None)`.

    Dùng làm đường dự phòng khi `requests` bị tường lửa/proxy công ty chặn riêng
    (thường là chặn theo tên miền API, hoặc chỉ cho trình duyệt đi qua proxy):
    trình duyệt dùng đúng proxy hệ thống và "vân tay" mạng thật nên hay vượt được
    chỗ mà thư viện HTTP rời không vượt nổi. Chậm hơn nên chỉ gọi sau khi
    `requests` đã thất bại.
    """
    import base64 as _b64
    import contextlib

    if driver is None:
        return None, None
    guard = driver_lock if driver_lock is not None else contextlib.nullcontext()
    try:
        with guard:
            driver.set_script_timeout(95)
            result = driver.execute_async_script(
                _BROWSER_FETCH_SCRIPT, method, url,
                (f"Bearer {bearer}" if bearer else None), payload, credentials)
    except Exception:
        return None, None
    if not result:
        return None, None
    status = result.get("status")
    b64 = result.get("data_b64")
    if not b64:
        return status, None
    try:
        return status, _b64.b64decode(b64)
    except Exception:
        return status, None


def close_popups(driver):
    """Đóng các cửa sổ quảng cáo/khảo sát che giao diện."""
    try:
        driver.execute_script(
            "document.querySelectorAll(\"[class*='close' i]\").forEach(function(e){"
            "if(e.offsetParent!==null){try{e.click();}catch(x){}}});")
    except Exception:
        pass
