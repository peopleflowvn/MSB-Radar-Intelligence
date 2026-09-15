# -*- coding: utf-8 -*-
"""
Đóng gói phần mềm MSB Radar Edge thành thư mục chạy được (--onedir) + file ZIP chia sẻ.

Vì sao dùng --onedir thay vì --onefile:
  - Khởi động nhanh hơn 2-3 lần (bản --onefile phải giải nén ra %TEMP% ở MỖI lần chạy).
  - Ít bị Windows SmartScreen và phần mềm diệt virus chặn hơn (không có hành vi tự giải nén).

Cách dùng:
    python build_exe.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import hashlib
import urllib.request

from app.version import APP_DISPLAY_NAME, APP_VERSION
from app.state_paths import local_state_dir

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "MSBRadarEdge"

# Ép cửa sổ lệnh in được tiếng Việt. Không có đoạn này, khi log được ghi ra file hoặc
# chạy trên máy dùng bảng mã cp1252 thì chỉ cần một chữ có dấu là script tắt ngang
# giữa chừng vì UnicodeEncodeError - đóng gói dở dang mà tưởng là lỗi PyInstaller.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ------------------------------------------------------------------------------
# Số phiên bản khai báo DUY NHẤT ở đây. Tên file ZIP và thông tin hiện trong
# "Properties" của file .exe đều sinh ra từ biến này, nên không bao giờ lệch nhau.
# ------------------------------------------------------------------------------
VERSION = APP_VERSION
RELEASE_FOLDER = f"{NAME}_v{VERSION}"
AUTHOR = "Le Hoang Tung"
CONTACT = "tunglehoang.vn@gmail.com - tunghr.io.vn"
DESCRIPTION = "MSB Radar Edge"

# ------------------------------------------------------------------------------
# Nơi xuất bản đóng gói. Mặc định ổ đĩa CỤC BỘ D:\MSBRadarBuild (không phải Google Drive):
# thư mục dự án đang nằm trong Drive, mà ổ ảo của Drive xoá/tạo/ghi đè file theo kiểu
# BẤT ĐỒNG BỘ - đã từng làm hỏng cả file .exe lẫn làm lệnh chép thư mục báo lỗi vô lý
# ("không tìm thấy" ngay trên thư mục nó vừa tạo). Build ra ổ nội bộ tránh hẳn lớp vấn
# đề này. Đặt biến môi trường MSB_RADAR_BUILD_OUT nếu muốn xuất ra nơi khác.
# ------------------------------------------------------------------------------
_D_KHADUNG = os.path.isdir("D:\\")
DEFAULT_OUT_DIR = r"D:\MSBRadarBuild" if _D_KHADUNG else os.path.join(HERE, "dist")
OUT_DIR = os.environ.get("MSB_RADAR_BUILD_OUT", DEFAULT_OUT_DIR)

LIBREOFFICE_URL = ("https://download.documentfoundation.org/libreoffice/stable/26.2.5/"
                   "win/x86_64/LibreOffice_26.2.5_Win_x86-64.msi")
LIBREOFFICE_SHA256 = "f15ba07bfcb0186986cf3171063506f5d207c11f8cc051ba0d135209e9e915f9"
SENSITIVE_RELEASE_NAMES = {
    "cauhinh.json", "tiendo.json", "nhatky.log", "loi_khoi_dong.log",
}
SENSITIVE_DB_SUFFIXES = (".db", ".db-wal", ".db-shm", ".khoa.json")


def _tree_mb(path):
    return sum(os.path.getsize(os.path.join(root, name))
               for root, _dirs, files in os.walk(path) for name in files) / 1024 / 1024


def _find_file(root, filename):
    for folder, _dirs, files in os.walk(root):
        if filename in files:
            return os.path.join(folder, filename)
    return ""


def _is_sensitive_release_path(relative_path):
    """Only runtime data beside the EXE is private; packaged dependencies may own .db files."""
    parts = relative_path.replace("/", "\\").lower().split("\\")
    package_parts = parts[1:] if parts and parts[0] == NAME.lower() else parts
    if package_parts and package_parts[0] == "_internal":
        return False
    basename = package_parts[-1] if package_parts else ""
    return (basename in SENSITIVE_RELEASE_NAMES
            or basename.endswith(SENSITIVE_DB_SUFFIXES)
            or "chrome_profile" in package_parts)


def write_release_zip(built_folder, zip_path):
    """Create a clean distributable and return paths excluded as private runtime data."""
    excluded = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, _dirs, files in os.walk(built_folder):
            for filename in files:
                absolute = os.path.join(root, filename)
                relative = os.path.relpath(absolute, os.path.dirname(built_folder))
                if _is_sensitive_release_path(relative):
                    excluded.append(relative)
                    continue
                archive.write(absolute, relative)
    return excluded


def _download_verified(url, target, expected_sha256):
    print(f"  Tải dependency: {os.path.basename(target)} ...")
    urllib.request.urlretrieve(url, target)
    digest = hashlib.sha256()
    with open(target, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest().lower() != expected_sha256.lower():
        raise RuntimeError(f"Sai SHA256 của {os.path.basename(target)}; đã hủy đóng gói.")


def prepare_portable_runtimes(build_root):
    """Stage every non-Python runtime. Missing required runtime fails the release."""
    cached = os.path.join(OUT_DIR, NAME, "_internal", "runtime")
    cached_required = (
        os.path.join(cached, "webview2", "msedgewebview2.exe"),
        os.path.join(cached, "tesseract", "tesseract.exe"),
        os.path.join(cached, "tesseract", "tessdata", "vie.traineddata"),
        os.path.join(cached, "libreoffice", "program", "soffice.exe"),
    )
    if all(os.path.isfile(path) for path in cached_required):
        print("  Runtime portable: dùng lại bộ đã xác minh từ bản build gần nhất.")
        return cached
    runtime = os.path.join(build_root, "portable_runtime")
    os.makedirs(runtime, exist_ok=True)

    # Fixed WebView2 from the build machine; copied beside the EXE, no system install needed.
    webview_base = next((path for path in (
        r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application",
        r"C:\Program Files\Microsoft\EdgeWebView\Application") if os.path.isdir(path)), "")
    versions = [os.path.join(webview_base, name) for name in os.listdir(webview_base)] if webview_base else []
    webview_source = next((path for path in sorted(versions, reverse=True)
                           if os.path.isfile(os.path.join(path, "msedgewebview2.exe"))), "")
    if not webview_source:
        raise RuntimeError("Máy build thiếu WebView2 Runtime; không tạo gói portable không đầy đủ.")
    webview_target = os.path.join(runtime, "webview2")
    shutil.copytree(webview_source, webview_target)

    # Tesseract and Vietnamese/English models are redistributable under Apache-2.0.
    tesseract_source = os.environ.get("MSB_RADAR_TESSERACT_DIR", r"C:\Program Files\Tesseract-OCR")
    if not os.path.isfile(os.path.join(tesseract_source, "tesseract.exe")):
        raise RuntimeError("Máy build thiếu Tesseract; không tạo gói không có OCR.")
    tesseract_target = os.path.join(runtime, "tesseract")
    shutil.copytree(tesseract_source, tesseract_target)
    local_models = os.path.join(local_state_dir(), "tessdata")
    for language in ("eng.traineddata", "vie.traineddata", "osd.traineddata"):
        candidates = (os.path.join(local_models, language),
                      os.path.join(tesseract_source, "tessdata", language))
        model = next((path for path in candidates if os.path.isfile(path)), "")
        if not model:
            raise RuntimeError(f"Thiếu mô hình OCR {language}; không tạo gói OCR không đầy đủ.")
        shutil.copy2(model, os.path.join(tesseract_target, "tessdata", language))

    # LibreOffice is extracted administratively, not installed on the user's computer.
    libre_source = os.environ.get("MSB_RADAR_LIBREOFFICE_DIR", "")
    if not os.path.isfile(os.path.join(libre_source, "program", "soffice.exe")):
        installed = (r"C:\Program Files\LibreOffice", r"C:\Program Files (x86)\LibreOffice")
        libre_source = next((path for path in installed
                             if os.path.isfile(os.path.join(path, "program", "soffice.exe"))), "")
    if not libre_source:
        msi = os.path.join(build_root, "LibreOffice.msi")
        extracted = os.path.join(build_root, "libreoffice_extract")
        _download_verified(LIBREOFFICE_URL, msi, LIBREOFFICE_SHA256)
        result = subprocess.run(["msiexec.exe", "/a", msi, "/qn", f"TARGETDIR={extracted}"],
                                timeout=600)
        soffice = _find_file(extracted, "soffice.exe")
        if result.returncode or not soffice:
            raise RuntimeError("Không giải nén được LibreOffice portable; đã hủy đóng gói.")
        libre_source = os.path.dirname(os.path.dirname(soffice))
    libre_target = os.path.join(runtime, "libreoffice")
    shutil.copytree(libre_source, libre_target)

    print(f"  Runtime portable: WebView2 {_tree_mb(webview_target):.0f} MB · "
          f"OCR {_tree_mb(tesseract_target):.0f} MB · LibreOffice {_tree_mb(libre_target):.0f} MB")
    return runtime


def is_app_running():
    """Bản đóng gói cũ có đang mở không?

    Windows KHOÁ mọi file .exe/.dll mà một tiến trình đã nạp, nên không thể xoá hay ghi
    đè thư mục dist khi phần mềm đang chạy. Phải kiểm tra NGAY TỪ ĐẦU: nếu để tới lúc
    chép file mới phát hiện thì người dùng đã phải chờ PyInstaller chạy xong mấy phút,
    rồi nhận một lỗi 'FileExistsError' chẳng nói lên điều gì.

    Phải HỎI DANH SÁCH TIẾN TRÌNH, không thử "mở file ở chế độ ghi" như cách thường làm:
    khi nơi xuất bản nằm trong Google Drive, ổ ảo của Drive KHÔNG áp dụng cơ chế khoá
    file .exe đang chạy như ổ NTFS - mở ghi vẫn thành công nên không phát hiện được gì,
    trong khi việc xoá/ghi đè thật sự thì vẫn hỏng.

    Chỉ chặn khi tiến trình đang chạy ĐÚNG từ thư mục đích (OUT_DIR) - máy có thể đang
    mở một bản MSBRadarEdge.exe khác ở nơi khác (vd. bản tải về trước đó để xem thử) mà
    không hề xung đột với lần đóng gói này, không nên chặn nhầm trường hợp đó.
    """
    if os.name != "nt":
        return False
    target = os.path.join(OUT_DIR, NAME, NAME + ".exe")
    try:
        out = subprocess.run(
            ["wmic", "process", "where", f"name='{NAME}.exe'", "get", "ExecutablePath"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        paths = [ln.strip() for ln in out.splitlines() if ln.strip()
                and ln.strip().lower() != "executablepath"]
        return any(os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(target))
                  for p in paths)
    except Exception:
        # Không dò được (vd wmic không có trên máy) -> không chặn oan; lỗi ghi đè thật
        # sự (nếu có) vẫn sẽ hiện ra rõ ràng ở bước chép file phía sau.
        return False


def remove_tree(path, tries=5):
    """Xoá thư mục, có thử lại - thư mục đích thường nằm trong Google Drive/OneDrive.

    shutil.rmtree(ignore_errors=True) trên ổ đồng bộ hay xoá KHÔNG HẾT mà vẫn im lặng
    báo thành công (dịch vụ đồng bộ đang giữ file). Lần đóng gói sau sẽ vấp đúng thư
    mục còn sót đó và chết ở bước chép, sau khi đã mất mấy phút chờ PyInstaller chạy.
    Thử lại vài lượt, chờ giữa các lượt cho dịch vụ đồng bộ nhả file ra.
    """
    for i in range(tries):
        if not os.path.exists(path):
            return True
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        time.sleep(1.5 * (i + 1))
    if os.path.exists(path):
        print(f"  ! Không xoá hết được {path} (Google Drive đang giữ file) - sẽ ghi đè.")
        return False
    return True


def write_version_info(path):
    """Sinh file thông tin phiên bản cho Windows (hiện khi bấm chuột phải > Properties)."""
    v = tuple(int(x) for x in VERSION.split(".")) + (0,) * (4 - len(VERSION.split(".")))
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v}, prodvers={v},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(u'042a04b0', [
        StringStruct(u'CompanyName', u'MSB Radar Edge'),
        StringStruct(u'FileDescription', u'{APP_DISPLAY_NAME}'),
        StringStruct(u'FileVersion', u'{VERSION}.0'),
        StringStruct(u'InternalName', u'{NAME}'),
        StringStruct(u'LegalCopyright', u'Tac gia: {AUTHOR}'),
        StringStruct(u'OriginalFilename', u'{NAME}.exe'),
        StringStruct(u'ProductName', u'{APP_DISPLAY_NAME}'),
        StringStruct(u'ProductVersion', u'{VERSION}.0'),
        StringStruct(u'Comments', u'{CONTACT}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1066, 1200])])
  ]
)
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def ensure_icon():
    """Bảo đảm có icon.ico nhúng ĐỦ NHIỀU CỠ.

    File .ico chỉ chứa 1 ảnh 256px sẽ bị Windows tự thu nhỏ lúc chạy -> icon nhoè ở
    thanh taskbar và Explorer. build_icon.py dựng sẵn từng cỡ nên luôn sắc nét.
    """
    icon = os.path.join(HERE, "app", "assets", "icon.ico")
    need_build = not os.path.exists(icon)
    if not need_build:
        with open(icon, "rb") as f:
            count = int.from_bytes(f.read(6)[4:6], "little")
        if count < 5:
            print(f"  ! icon.ico chỉ có {count} cỡ -> dựng lại cho đủ.")
            need_build = True
    if need_build:
        r = subprocess.run([sys.executable, os.path.join(HERE, "build_icon.py")], cwd=HERE)
        if r.returncode != 0 or not os.path.exists(icon):
            print("  ! Không tạo được icon - sẽ đóng gói với icon mặc định của Python.")
            return None
    with open(icon, "rb") as f:
        count = int.from_bytes(f.read(6)[4:6], "little")
    print(f"  Icon: {os.path.relpath(icon, HERE)} ({count} cỡ nhúng sẵn)")
    return icon


def check_smoke_test():
    """Chạy bộ kiểm tra nhanh trước khi đóng gói - chặn việc phát hành bản đang lỗi."""
    st = os.path.join(HERE, "tests", "smoke_test.py")
    if not os.path.exists(st):
        return True
    print("  Đang chạy tests/smoke_test.py ...")
    r = subprocess.run([sys.executable, st], cwd=HERE,
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print("\n*** DỪNG: smoke test THẤT BẠI - sửa lỗi trên rồi hãy đóng gói. ***")
        return False
    print("  Smoke test: OK")
    return True


def install_exe_runtime_config(built_folder):
    """Cấu hình CLR trên AppDomain mặc định, thay vì tạo AppDomain riêng trong Python."""
    source = os.path.join(HERE, "app", "runtime.config")
    target = os.path.join(built_folder, NAME + ".exe.config")
    shutil.copy2(source, target)
    return target


def restore_python_runtime_dlls(built_folder):
    """Ngăn DLL trùng tên từ LibreOffice ghi đè DLL mà CPython/PyInstaller cần."""
    internal = os.path.join(built_folder, "_internal")
    restored = []
    # LibreOffice kèm Python riêng và một sqlite3.dll không ABI-compatible với
    # _sqlite3.pyd của Python dùng để build ứng dụng. PyInstaller có thể hoist DLL
    # đó lên _internal theo tên file, khiến sqlite3.connect crash native 0xc0000005.
    for name in ("sqlite3.dll",):
        source = os.path.join(sys.base_prefix, "DLLs", name)
        if not os.path.isfile(source):
            raise RuntimeError(f"Python build environment thiếu {source}")
        target = os.path.join(internal, name)
        shutil.copy2(source, target)
        with open(source, "rb") as source_stream, open(target, "rb") as target_stream:
            source_hash = hashlib.sha256(source_stream.read()).digest()
            target_hash = hashlib.sha256(target_stream.read()).digest()
        if source_hash != target_hash:
            raise RuntimeError(f"Không khôi phục chính xác {name} vào bản đóng gói.")
        restored.append(target)
    print("  DLL Python đã được cô lập khỏi runtime LibreOffice: "
          + ", ".join(os.path.basename(path) for path in restored))
    return restored


def verify_web_assets(built_folder):
    """Chặn phát hành giao diện thiếu file hoặc CSS vỡ cấu trúc."""
    web_root = os.path.join(built_folder, "_internal", "app", "web")
    required = ("index.html", "styles.css", "app.js")
    missing = [name for name in required if not os.path.isfile(os.path.join(web_root, name))]
    if missing:
        raise RuntimeError(f"Thiếu tài nguyên giao diện: {', '.join(missing)}")
    css_path = os.path.join(web_root, "styles.css")
    with open(css_path, encoding="utf-8") as stream:
        css = stream.read()
    if css.count("{") != css.count("}"):
        raise RuntimeError(
            f"CSS không cân bằng ngoặc: {css.count('{')} mở / {css.count('}')} đóng")
    for selector in (".splash-overlay", ".modal-overlay", ".runtime-readiness-dialog"):
        if selector not in css:
            raise RuntimeError(f"CSS thiếu selector bắt buộc {selector}")
    print("  Tài nguyên web: OK (HTML, JavaScript, CSS cân bằng)")
    return True


def verify_packaged_startup(built_exe):
    """Chạy chính EXE phát hành và đợi tín hiệu WebView2 đã nạp trang thành công."""
    marker_dir = tempfile.mkdtemp(prefix="msbradar_probe_")
    marker = os.path.join(marker_dir, "ready.txt")
    env = os.environ.copy()
    env["MSB_RADAR_PACKAGED_STARTUP_PROBE"] = "1"
    env["MSB_RADAR_PACKAGED_STARTUP_MARKER"] = marker
    env["MSB_RADAR_RUNTIME_DIR"] = marker_dir
    print("  Đang chạy kiểm tra EXE thật (.NET + WinForms + WebView2)...")
    process = subprocess.Popen([built_exe], cwd=os.path.dirname(built_exe), env=env)
    try:
        return_code = process.wait(timeout=45)
        if return_code != 0 or not os.path.isfile(marker):
            raise RuntimeError(
                f"EXE không vượt qua startup probe (exit={return_code}, marker={os.path.isfile(marker)}).")
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        raise RuntimeError("EXE không nạp xong WebView2 trong 45 giây.")
    finally:
        shutil.rmtree(marker_dir, ignore_errors=True)
    print("  Startup probe: OK")
    return True


def main():
    t0 = time.time()
    print(f"=== Đóng gói {NAME} v{VERSION} ===\n")

    if is_app_running():
        print("*** DỪNG: MSBRadarEdge.exe của bản đóng gói trước ĐANG CHẠY.\n"
              "    Windows khoá file .exe đang mở nên không ghi đè được.\n"
              "    Hãy ĐÓNG cửa sổ MSB Radar Edge rồi chạy lại lệnh này. ***")
        sys.exit(1)

    if not check_smoke_test():
        sys.exit(1)
    icon = ensure_icon()

    # Dọn bản build cũ
    for d in ("build", "dist", "__pycache__"):
        p = os.path.join(HERE, d)
        if os.path.isdir(p):
            remove_tree(p)
    spec = os.path.join(HERE, NAME + ".spec")
    if os.path.exists(spec):
        os.remove(spec)

    # QUAN TRỌNG: build ra ổ đĩa CỤC BỘ, không build thẳng vào thư mục này vì
    # nó nằm trong Google Drive. PyInstaller ghi rồi vá lại file .exe nhiều lượt (gắn
    # icon, thông tin phiên bản, manifest); kiểu ghi "nhảy cóc" đó bị Google Drive đồng
    # bộ xen vào làm hỏng file - tạo ra .exe đủ dung lượng nhưng chạy lên là báo lỗi.
    # Dùng đường dẫn thật ngắn: cây LibreOffice có nhiều tên file sâu; đặt dưới
    # %TEMP% dài có thể vượt MAX_PATH của một số API Windows khi copytree.
    os.makedirs(OUT_DIR, exist_ok=True)
    build_root = tempfile.mkdtemp(prefix="b_", dir=OUT_DIR)
    dist_dir = os.path.join(build_root, "dist")
    work_dir = os.path.join(build_root, "build")
    vinfo = write_version_info(os.path.join(build_root, "version_info.txt"))
    try:
        portable_runtime = prepare_portable_runtimes(build_root)
    except Exception as exc:
        shutil.rmtree(build_root, ignore_errors=True)
        print(f"\n*** DỪNG: không chuẩn bị đủ runtime portable: {exc} ***")
        sys.exit(1)

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",                 # không hiện cửa sổ đen console
        "--name", NAME,
        "--distpath", dist_dir,
        "--workpath", work_dir,
        "--specpath", build_root,

        # LƯU Ý: phải là "webview" (tên module để import), KHÔNG phải "pywebview"
        # (tên gói khi cài bằng pip). Ghi nhầm thành pywebview thì PyInstaller chỉ in
        # một dòng WARNING rồi bỏ qua, build vẫn "thành công" nhưng file .exe thiếu
        # toàn bộ lõi giao diện -> mở lên là lỗi hoặc cửa sổ trắng.
        "--collect-all", "webview",
        # pythonnet kèm thư viện .NET (Python.Runtime.dll) mà pywebview cần để dùng
        # nhân trình duyệt Edge WebView2 trên Windows.
        "--collect-all", "pythonnet",
        "--collect-all", "undetected_chromedriver",

        "--add-data", f"{os.path.join(HERE, 'app', 'web')}{os.pathsep}app/web",
        "--add-data", f"{portable_runtime}{os.pathsep}runtime",
        "--hidden-import", "openpyxl",
        "--hidden-import", "fitz",
        "--hidden-import", "docx",
        "--hidden-import", "selenium",
        "--hidden-import", "requests",
        "--hidden-import", "clr",

        # Bỏ các nền tảng pywebview không dùng trên Windows (giảm dung lượng, hết cảnh báo)
        "--exclude-module", "webview.platforms.android",
        "--exclude-module", "webview.platforms.cocoa",
        "--exclude-module", "webview.platforms.gtk",
        "--exclude-module", "webview.platforms.qt",

        # Bỏ các thư viện nặng không dùng đến
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "PyQt5",
        "--exclude-module", "PySide2",
        "--exclude-module", "notebook",
        "--exclude-module", "IPython",

        "--version-file", vinfo,
    ]
    if icon:
        args += ["--icon", icon,
                 "--add-data", f"{icon}{os.pathsep}assets"]
    args.append(os.path.join(HERE, "main.py"))

    print("\n  Đang đóng gói, mất khoảng 1-3 phút...\n")
    r = subprocess.run(args, cwd=HERE)
    if r.returncode != 0:
        shutil.rmtree(build_root, ignore_errors=True)
        print("\n*** ĐÓNG GÓI THẤT BẠI ***")
        sys.exit(r.returncode)

    built_folder = os.path.join(dist_dir, NAME)
    built_exe = os.path.join(built_folder, NAME + ".exe")
    if not os.path.exists(built_exe):
        shutil.rmtree(build_root, ignore_errors=True)
        print(f"\n*** ĐÓNG GÓI THẤT BẠI: không thấy {NAME}.exe ***")
        sys.exit(1)

    install_exe_runtime_config(built_folder)
    restore_python_runtime_dlls(built_folder)
    verify_web_assets(built_folder)

    try:
        verify_packaged_startup(built_exe)
    except Exception as exc:
        shutil.rmtree(build_root, ignore_errors=True)
        print(f"\n*** DỪNG: EXE ĐÓNG GÓI KHÔNG KHỞI ĐỘNG ỔN ĐỊNH: {exc} ***")
        sys.exit(1)

    # Hướng dẫn xử lý prerequisite/MOTW phải nằm ngay cạnh EXE và có trong ZIP.
    shutil.copy2(os.path.join(HERE, "HUONG_DAN_KHOI_DONG.txt"), built_folder)

    # Kiểm tra phần giao diện web thực sự nằm trong bản đóng gói (thiếu là mở lên trắng trơn)
    internal = os.path.join(built_folder, "_internal")
    web_index = None
    for base in (internal, built_folder):
        p = os.path.join(base, "app", "web", "index.html")
        if os.path.exists(p):
            web_index = p
            break
    if not web_index:
        print("\n*** CẢNH BÁO: không thấy app/web/index.html trong bản đóng gói -"
              " mở lên sẽ bị cửa sổ trắng! ***")

    # Tạo GÓI ZIP TRƯỚC - đây mới là thứ đem gửi cho người khác nên phải chắc chắn có.
    # Việc chép ra thư mục để chạy thử chỉ là tiện ích, làm sau và cho phép hỏng.
    dist_here = OUT_DIR
    os.makedirs(dist_here, exist_ok=True)
    target_folder = os.path.join(dist_here, RELEASE_FOLDER)

    print("\n  Đang nén gói ZIP để chia sẻ...")
    zip_path = os.path.join(dist_here, f"{NAME}_v{VERSION}_Portable.zip")

    # QUAN TRỌNG - nén từ THƯ MỤC GỐC PyInstaller vừa tạo (trong %TEMP%), KHÔNG nén từ
    # thư mục dist. Vì mỗi lần chạy thử bản đóng gói, phần mềm sinh ra ngay cạnh file
    # .exe: cauhinh.json (CHỨA EMAIL VÀ MẬT KHẨU dạng chữ thường), cơ sở dữ liệu ứng
    # viên, nhật ký, phiên đăng nhập Chrome... Nén từ dist là gửi thẳng toàn bộ những
    # thứ đó cho đồng nghiệp/khách hàng.
    bo_qua = write_release_zip(built_folder, zip_path)
    if bo_qua:
        print(f"  ! Đã loại {len(bo_qua)} file dữ liệu cá nhân khỏi gói ZIP: "
              f"{', '.join(bo_qua[:5])}")

    # Kiểm tra lại lần cuối - thà dừng còn hơn gửi nhầm dữ liệu cá nhân đi
    con_sot = [n for n in zipfile.ZipFile(zip_path).namelist()
               if _is_sensitive_release_path(n)]
    if con_sot:
        print(f"\n*** DỪNG: gói ZIP còn lẫn dữ liệu cá nhân: {con_sot} ***")
        sys.exit(1)

    # Tiện ích: chép ra thư mục để chạy thử ngay. Thất bại cũng không sao - gói ZIP ở
    # trên mới là bản phát hành, giải nén ra là dùng được.
    print(f"  Đang chép ra {dist_here} để chạy thử...")
    chep_ok = False
    for lan in range(3):
        remove_tree(target_folder)
        try:
            shutil.copytree(built_folder, target_folder, dirs_exist_ok=True)
            chep_ok = True
            break
        except (OSError, shutil.Error) as e:
            if lan == 2:
                print(f"  ! Không chép được ra {dist_here}: {str(e)[:120]}")
                print("    Không sao - hãy giải nén gói ZIP ở trên để chạy.")
            else:
                time.sleep(4 * (lan + 1))

    shutil.rmtree(build_root, ignore_errors=True)

    def mb(p):
        return os.path.getsize(p) / 1024 / 1024

    print("\n" + "=" * 68)
    print(f"XONG sau {time.time() - t0:.0f} giây")
    print(f"  Nơi xuất bản đóng gói  : {dist_here}")
    print(f"  Gói ZIP phát hành      : {os.path.basename(zip_path)}  ({mb(zip_path):.0f} MB)")
    if chep_ok:
        folder_mb = sum(os.path.getsize(os.path.join(r_, f))
                        for r_, _d, fs in os.walk(target_folder)
                        for f in fs) / 1024 / 1024
        print(f"  Thư mục chạy trực tiếp : {target_folder}  ({folder_mb:.0f} MB)")
    print("=" * 68)
    print("\nCách dùng:")
    if chep_ok:
        print(f"  1. Chạy thử ngay  : mở {os.path.join(target_folder, NAME + '.exe')}")
    print(f"  2. Gửi đồng nghiệp: gửi file ZIP, giải nén ra rồi bấm {NAME}.exe")
    print("     (Máy nhận chỉ cần Windows 10 22H2/Windows 11 x64 và Google Chrome.)")
    print("     WebView2, OCR Việt/Anh, LibreOffice và thư viện đã nằm trong gói portable.")
    print("     Gói ZIP KHÔNG chứa tài khoản, dữ liệu ứng viên hay phiên đăng nhập của bạn -")
    print("     máy nhận sẽ tự khai báo tài khoản riêng ở màn hình Cấu hình lần đầu.")


if __name__ == "__main__":
    main()
