# -*- coding: utf-8 -*-
"""
Cấu hình ứng dụng - lưu trong file JSON cạnh chương trình để người dùng có thể
chỉnh trực tiếp trên giao diện mà không cần biết lập trình.
"""
import json
import hashlib
import os
import sys
import copy
from dataclasses import dataclass, asdict, field

from .state_paths import local_state_dir


def app_dir() -> str:
    """Thư mục chứa chương trình (hoạt động cả khi chạy .exe đã đóng gói)."""
    if os.environ.get("MSB_RADAR_PACKAGED_STARTUP_PROBE") == "1":
        probe_dir = os.environ.get("MSB_RADAR_RUNTIME_DIR", "")
        if probe_dir:
            os.makedirs(probe_dir, exist_ok=True)
            return probe_dir
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def asset_path(name: str) -> str:
    """Đường dẫn tới file trong app/assets/ - hoạt động cả khi chạy dev lẫn .exe đóng gói
    (PyInstaller giải nén tài nguyên vào thư mục tạm sys._MEIPASS lúc chạy)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", app_dir())
        return os.path.join(base, "assets", name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)


CONFIG_PATH = os.path.join(app_dir(), "cauhinh.json")
# DPAPI chỉ giải mã được với đúng tài khoản Windows. Vì vậy kho bí mật phải nằm
# ở máy cục bộ, không đặt cạnh ứng dụng trong thư mục có thể đồng bộ Google Drive.
_LOCAL_STATE_DIR = ""
SECRET_PATH = ""


def refresh_state_paths() -> str:
    """Tính lại đường dẫn state cục bộ từ app.state_paths.

    Gọi lúc import, và gọi lại sau migrate_legacy_state() vì lúc đó thư mục có
    hiệu lực đã đổi. Các hàm khác đọc SECRET_PATH qua global lúc chạy nên chỉ
    cần gán lại ở đây là toàn bộ ứng dụng thấy đường dẫn mới.
    """
    global _LOCAL_STATE_DIR, SECRET_PATH
    _LOCAL_STATE_DIR = local_state_dir()
    SECRET_PATH = os.path.join(_LOCAL_STATE_DIR, "secrets.json")
    return _LOCAL_STATE_DIR


refresh_state_paths()
STATE_PATH = os.path.join(app_dir(), "tiendo.json")
LOG_MAX_BYTES = 5 * 1024 * 1024   # 5 MB - chạy hẹn giờ nhiều tháng liền, cần giới hạn nhật ký
LOG_PATH = os.path.join(app_dir(), "nhatky.log")


def normalize_account(value) -> str:
    """Chuẩn hóa email tài khoản để làm khóa phạm vi đồng bộ ổn định."""
    return str(value or "").strip().lower()


def account_for_source(cfg, source) -> str:
    """Trả tài khoản cấu hình đúng của từng nguồn tuyển dụng."""
    fields = {
        "topcv": "email",
        "vietnamworks": "vietnamworks_email",
        "careerviet": "careerviet_email",
        "vieclam24h": "vieclam24h_email",
        "itviec": "itviec_email",
        "joboko": "joboko_email",
        "jobsgo": "jobsgo_email",
    }
    return normalize_account(getattr(cfg, fields.get(source, "email"), ""))


#: Nguồn tuyển dụng dùng cặp field `<src>_email` / `<src>_password` (TopCV là ngoại
#: lệ: `email` / `password`). Dùng cho việc mồi tài khoản từ .env.
_ENV_SEED_SOURCES = ("topcv", "vietnamworks", "careerviet", "vieclam24h", "itviec", "joboko", "jobsgo")


def _read_env_files():
    """Đọc các file .env (nếu có) thành dict. Parser tối giản, không thêm dependency."""
    values = {}
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    try:
        candidates.append(os.path.join(local_state_dir(), ".env"))
    except Exception:
        pass
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in values:
                        values[key] = val
        except OSError:
            continue
    return values


def _seed_accounts_from_env(cfg, store) -> bool:
    """Mồi `<src>_email`/`<src>_password` từ .env + biến môi trường khi đang trống.
    Trả True nếu có thay đổi. Không đè giá trị người dùng đã nhập."""
    env = {**_read_env_files(), **os.environ}
    changed = False
    have_account_list = bool(cfg.provider_accounts)
    for source in _ENV_SEED_SOURCES:
        prefix = "TOPCV" if source == "topcv" else source.upper()
        email = normalize_account(env.get(f"{prefix}_EMAIL", ""))
        password = str(env.get(f"{prefix}_PASSWORD", "") or "")
        if not email:
            continue
        email_field = "email" if source == "topcv" else f"{source}_email"
        password_field = "password" if source == "topcv" else f"{source}_password"
        if getattr(cfg, email_field, "").strip():
            continue                       # người dùng đã cấu hình -> bỏ qua
        setattr(cfg, email_field, email)
        changed = True
        if password:
            try:
                store.set(password_field, password)
            except Exception:              # noqa: BLE001 - kho bí mật hỏng vẫn chạy được phiên này
                pass
            setattr(cfg, password_field, password)
        if have_account_list and not any(
                row.get("source") == source for row in cfg.provider_accounts):
            account_id = hashlib.sha256(f"{source}:{email}".encode()).hexdigest()[:12]
            cfg.provider_accounts.append({
                "id": account_id, "source": source, "email": email,
                "label": email, "enabled": True})
            if password:
                try:
                    store.set("account:" + account_id, password)
                except Exception:          # noqa: BLE001
                    pass
    return changed


def account_profile_dir(base_dir, account) -> str:
    """Tách phiên Chrome theo tài khoản mà không để lộ email trong đường dẫn."""
    normalized = normalize_account(account)
    if not normalized:
        return base_dir
    account_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return os.path.join(base_dir, f"account_{account_key}")


def rotate_log_if_needed():
    """Cắt bớt nhật ký nếu quá lớn (giữ lại phần cuối) - tránh phình to khi chạy hẹn giờ dài ngày."""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            with open(LOG_PATH, "rb") as f:
                f.seek(-LOG_MAX_BYTES // 2, os.SEEK_END)
                tail = f.read()
            with open(LOG_PATH, "wb") as f:
                f.write(b"--- (da cat bot nhat ky cu) ---\n")
                f.write(tail)
    except Exception:
        pass


@dataclass
class AppConfig:
    # --- Tài khoản TopCV ---
    email: str = ""
    password: str = ""
    vietnamworks_email: str = ""
    vietnamworks_password: str = ""
    careerviet_email: str = ""
    careerviet_password: str = ""
    vieclam24h_email: str = ""
    vieclam24h_password: str = ""
    itviec_email: str = ""
    itviec_password: str = ""
    joboko_email: str = ""
    joboko_password: str = ""
    # Joboko điều khiển cả cửa sổ Chrome suốt lượt tải nên mặc định chạy ẩn cho
    # nhẹ máy; tự bật cửa sổ khi cần đăng nhập.
    joboko_headless: bool = True
    jobsgo_email: str = ""
    jobsgo_password: str = ""
    # Danh sách tài khoản mới. Mật khẩu không nằm trong JSON mà lưu DPAPI theo id.
    provider_accounts: list = field(default_factory=list)
    schedule_sources: list = field(default_factory=list)
    schedule_jobs: list = field(default_factory=list)

    # --- Nơi lưu dữ liệu ---
    # Mặc định lưu NGAY CẠNH file .exe - để copy sang máy khác (ổ đĩa/đường dẫn khác)
    # vẫn tự chạy được mà không cần sửa gì. Muốn đồng bộ nhiều máy qua Google Drive thì
    # vào tab Cấu hình đổi 3 đường dẫn này sang thư mục Google Drive đã đồng bộ.
    cv_folder: str = field(default_factory=lambda: os.path.join(app_dir(), "CV"))
    # Cơ sở dữ liệu SQLite - nơi lưu chính thức thông tin ứng viên
    db_path: str = field(default_factory=lambda: os.path.join(app_dir(), "du_lieu_ung_vien.db"))
    # Thư mục mặc định khi bấm "Xuất Excel/CSV"
    export_folder: str = field(default_factory=app_dir)
    # (Chỉ dùng để chuyển dữ liệu từ bản cũ sang, không còn dùng để lưu)
    excel_path: str = field(default_factory=lambda: os.path.join(app_dir(), "CV TopCV.xlsx"))
    excel_sheet: str = "TopCV"

    # --- Cách đặt tên file CV ---
    # {id} = mã CV, {ten} = họ tên, {vitri} = vị trí ứng tuyển, {ngay} = ngày ứng tuyển
    filename_pattern: str = "{id}_{ten}"

    # --- Hiệu năng ---
    concurrency: int = 4          # số CV tải cùng lúc (1-8). Cao quá dễ bị TopCV chặn.
    delay_ms: int = 250           # nghỉ giữa các lượt tải (mili giây)
    page_delay_ms: int = 400      # nghỉ giữa các trang danh sách

    # --- Trình duyệt ---
    headless: bool = False        # ẩn cửa sổ Chrome khi đăng nhập lấy phiên
    chrome_profile: str = ""      # để trống = tự tạo cạnh chương trình
    chrome_version: int = 0       # 0 = tự dò phiên bản Chrome
    chromedriver_path: str = ""   # đường dẫn chromedriver có sẵn (mạng chặn Google thì đỡ phải tải)

    # --- Mạng công ty: proxy & chứng chỉ TLS ---
    proxy_url: str = ""           # "" = tự dò (Windows/biến môi trường); "off" = đi thẳng; hoặc http://host:port
    ssl_verify: bool = True       # tắt để bỏ qua kiểm tra chứng chỉ khi proxy soi SSL mà chưa cài được CA
    ssl_ca_bundle: str = ""       # đường dẫn file CA nội bộ của công ty (.pem/.crt)

    # --- Hẹn giờ ---
    schedule_enabled: bool = False
    schedule_interval_min: int = 60      # chạy lại mỗi N phút
    schedule_start_time: str = ""        # "" = chạy ngay; hoặc "HH:MM"; hoặc "YYYY-MM-DD HH:MM"
    schedule_mode: str = "moi"           # "moi" = chỉ CV mới, "tatca" = quét lại toàn bộ
    schedule_source: str = "topcv"       # nguồn chạy định kỳ
    autostart_schedule: bool = False     # tự bật hẹn giờ ngay khi mở chương trình

    # --- Khác ---
    retry_failed: bool = True     # tự thử lại các CV lỗi ở lần chạy sau
    skip_existing_file: bool = True   # nếu file CV đã tồn tại trên đĩa thì bỏ qua

    parsing_enabled: bool = True
    parsing_ocr_enabled: bool = True
    parsing_min_native_chars: int = 120
    parsing_max_pages: int = 30
    parsing_batch_size: int = 500
    parsing_max_file_mb: int = 50
    parsing_max_sheet_cells: int = 200000
    parsing_delay_ms: int = 100

    # --- Đồng bộ lên MSB Radar Hub ---
    # hub_api_key KHÔNG nằm trong dataclass: giống mọi mật khẩu khác, nó được
    # lưu qua DPAPI và bị loại khỏi cauhinh.json khi save().
    # Đồng bộ do PipelineCoordinator kích hoạt theo delta - không còn công tắc
    # bật/tắt hay chu kỳ; chỉ cần địa chỉ Hub + API key là đủ.
    hub_url: str = ""
    hub_batch_size: int = 50

    # --- Nhận diện thương hiệu & Giao diện (Theme & Branding) ---
    app_name: str = "MSB Radar Edge"
    app_tagline: str = "Trạm Thu Thập & Xử Lý CV Ngoại Biên"
    app_icon: str = "⚡"
    app_logo_url: str = ""
    theme_mode: str = "dark"          # "dark" | "light" | "auto"
    color_preset: str = "amber_gold"  # "amber_gold" | "ocean_blue" | "crimson_red" | "emerald_green" | "royal_purple" | "cyber_cyan" | "custom"
    custom_color: str = "#F59E0B"
    table_density: str = "normal"     # "compact" | "normal" | "comfortable"


    def profile_dir(self) -> str:
        """Nơi lưu phiên đăng nhập trình duyệt.

        Mặc định đặt trong ổ đĩa máy (AppData), KHÔNG đặt cạnh file .exe. Lý do: rất
        nhiều người để phần mềm trong thư mục Google Drive/OneDrive, mà profile Chrome
        gồm hàng nghìn file nhỏ - khi nằm trên ổ đồng bộ thì:
          • Chrome mở CHẬM hẳn (ổ Google Drive là ổ ảo: file chưa có sẵn trong máy thì
            mỗi lần đọc là một lần tải qua mạng).
          • Vài trăm MB dữ liệu tạm bị đồng bộ lên mây một cách vô ích.
          • Hai máy chạy cùng lúc dễ làm hỏng profile.
        Đây chỉ là bộ nhớ phiên đăng nhập, không phải dữ liệu ứng viên, nên không cần
        đi theo phần mềm khi chép sang máy khác - máy mới chỉ cần đăng nhập lại một lần.
        Người dùng vẫn có thể tự chỉ định đường dẫn khác trong tab Cấu hình.
        """
        if self.chrome_profile:
            return account_profile_dir(self.chrome_profile, self.email)
        return account_profile_dir(
            os.path.join(local_state_dir(), "chrome_profile"), self.email)

    def vietnamworks_profile_dir(self) -> str:
        """Profile tách riêng để phiên VietnamWorks không xung đột với TopCV."""
        return account_profile_dir(
            os.path.join(local_state_dir(), "vietnamworks_profile"), self.vietnamworks_email)

    def careerviet_profile_dir(self) -> str:
        """Profile tách riêng để phiên CareerViet không xung đột với nguồn khác."""
        return account_profile_dir(
            os.path.join(local_state_dir(), "careerviet_profile"), self.careerviet_email)

    def vieclam24h_profile_dir(self) -> str:
        """Profile tách riêng để phiên Việc Làm 24h không xung đột với nguồn khác."""
        return account_profile_dir(
            os.path.join(local_state_dir(), "vieclam24h_profile"), self.vieclam24h_email)

    def itviec_profile_dir(self) -> str:
        """Profile tách riêng để phiên ITViec không xung đột với nguồn khác."""
        return account_profile_dir(
            os.path.join(local_state_dir(), "itviec_profile"), self.itviec_email)

    def joboko_profile_dir(self) -> str:
        """Profile tách riêng để phiên Joboko không xung đột với nguồn khác."""
        return account_profile_dir(
            os.path.join(local_state_dir(), "joboko_profile"), self.joboko_email)

    def jobsgo_profile_dir(self) -> str:
        """Profile tách riêng để phiên JobsGO không xung đột với nguồn khác."""
        return account_profile_dir(
            os.path.join(local_state_dir(), "jobsgo_profile"), self.jobsgo_email)

    def accounts_for_source(self, source, enabled_only=True):
        rows = [dict(row) for row in self.provider_accounts
                if row.get("source") == source and (not enabled_only or row.get("enabled", True))]
        if rows:
            return rows
        if self.provider_accounts:
            return []
        email = account_for_source(self, source)
        if email:
            return [{"id": hashlib.sha256(f"{source}:{email}".encode()).hexdigest()[:12],
                     "source": source, "email": email, "enabled": True, "label": email}]
        return []

    def for_account(self, account):
        """Tạo cấu hình runtime tương thích provider cũ cho đúng một tài khoản."""
        cfg = copy.copy(self)
        source = account.get("source", "topcv")
        email = normalize_account(account.get("email"))
        field = {"topcv": "email", "vietnamworks": "vietnamworks_email",
                 "careerviet": "careerviet_email", "vieclam24h": "vieclam24h_email",
                 "itviec": "itviec_email", "joboko": "joboko_email",
                 "jobsgo": "jobsgo_email"}.get(source, "email")
        password_field = "password" if source == "topcv" else source + "_password"
        setattr(cfg, field, email)
        from .secrets import SecretStore
        secret = SecretStore(SECRET_PATH).get("account:" + str(account.get("id") or ""))
        if secret:
            setattr(cfg, password_field, secret)
        return cfg

    # ---------- Lưu / nạp ----------
    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        plaintext_secrets = {}
        config_warning = ""
        config_source = CONFIG_PATH
        data = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                backup = CONFIG_PATH + ".bak"
                try:
                    with open(backup, encoding="utf-8") as f:
                        data = json.load(f)
                    config_source = backup
                    config_warning = "Cấu hình chính bị lỗi; đã khôi phục từ bản sao lưu."
                except Exception:
                    data = {}
                    config_warning = "Không đọc được cấu hình; ứng dụng đang dùng mặc định."
            for k, v in data.items():
                if hasattr(cfg, k):
                    if k.endswith("password") and v:
                        plaintext_secrets[k] = str(v)
                    else:
                        setattr(cfg, k, v)
        # Tự chuyển cấu hình một tài khoản/kênh cũ sang danh sách mới, không làm mất dữ liệu.
        if "provider_accounts" not in data:
            for source in ("topcv", "vietnamworks", "careerviet", "vieclam24h", "itviec",
                           "joboko", "jobsgo"):
                email = account_for_source(cfg, source)
                if email:
                    cfg.provider_accounts.append({
                        "id": hashlib.sha256(f"{source}:{email}".encode()).hexdigest()[:12],
                        "source": source, "email": email, "label": email, "enabled": True})
        # Giữ nguyên lịch cũ sau khi nâng cấp sang mô hình nhiều lịch.
        if "schedule_jobs" not in data and cfg.schedule_enabled:
            cfg.schedule_jobs.append({
                "id": "legacy_schedule", "name": "Lịch tự động cũ",
                "sources": cfg.schedule_sources or [cfg.schedule_source],
                "account_ids": [], "mode": cfg.schedule_mode,
                "interval_min": max(15, int(cfg.schedule_interval_min or 60)),
                "start_time": cfg.schedule_start_time, "enabled": True,
                "last_run_at": "", "last_status": "Chưa chạy",
            })
        from .secrets import SecretStore, SecretStoreError
        store = SecretStore(SECRET_PATH)
        secret_fields = ("password", "vietnamworks_password", "careerviet_password",
                         "vieclam24h_password", "itviec_password", "joboko_password",
                         "jobsgo_password")
        migrated = False
        for field_name in secret_fields:
            legacy = plaintext_secrets.get(field_name, "")
            if legacy:
                try:
                    store.set(field_name, legacy)
                    migrated = True
                except SecretStoreError:
                    # Giữ trong bộ nhớ cho phiên hiện tại nhưng không ghi plaintext lại.
                    setattr(cfg, field_name, legacy)
                    continue
            secured = store.get(field_name)
            if secured:
                setattr(cfg, field_name, secured)
        # Mồi tài khoản nguồn tuyển dụng từ .env / biến môi trường khi CHƯA có -
        # để triển khai máy mới không phải gõ tay. Không đè cấu hình đã nhập.
        seeded = _seed_accounts_from_env(cfg, store)
        if migrated or seeded:
            cfg.save()
        cfg._load_warning = config_warning
        cfg._loaded_from = config_source
        return cfg

    def save(self) -> None:
        from .secrets import SecretStore
        store = SecretStore(SECRET_PATH)
        data = asdict(self)
        for field_name in ("password", "vietnamworks_password", "careerviet_password",
                           "vieclam24h_password", "itviec_password", "joboko_password",
                           "jobsgo_password"):
            value = data.pop(field_name, "")
            if value:
                store.set(field_name, value)
        temporary = CONFIG_PATH + ".tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # Bản sao cũng dùng dữ liệu đã loại mật khẩu; tuyệt đối không sao chép
        # nguyên file cấu hình legacy vì có thể giữ bí mật dạng rõ.
        backup_temporary = CONFIG_PATH + ".bak.tmp"
        try:
            with open(backup_temporary, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(backup_temporary, CONFIG_PATH + ".bak")
        except OSError:
            try:
                os.remove(backup_temporary)
            except OSError:
                pass
        os.replace(temporary, CONFIG_PATH)

    # ---------- Hub ----------
    HUB_API_KEY_SECRET = "hub_api_key"

    def hub_api_key(self) -> str:
        """API key của Hub, đọc từ kho DPAPI chứ không từ cauhinh.json."""
        from .secrets import SecretStore
        return SecretStore(SECRET_PATH).get(self.HUB_API_KEY_SECRET) or ""

    def set_hub_api_key(self, value) -> None:
        from .secrets import SecretStore
        SecretStore(SECRET_PATH).set(self.HUB_API_KEY_SECRET, str(value or ""))

    def hub_ready(self) -> bool:
        """Đủ điều kiện để thực sự gửi dữ liệu lên Hub."""
        return bool(self.hub_url.strip() and self.hub_api_key())

    def has_password(self, source="topcv") -> bool:
        field_name = {
            "topcv": "password", "vietnamworks": "vietnamworks_password",
            "careerviet": "careerviet_password", "vieclam24h": "vieclam24h_password",
            "itviec": "itviec_password", "joboko": "joboko_password",
            "jobsgo": "jobsgo_password",
        }.get(source, "password")
        return bool(getattr(self, field_name, ""))

    def needs_setup(self) -> bool:
        """Chỉ báo chưa có bất kỳ nguồn nào sẵn sàng; không khóa ứng dụng theo TopCV."""
        return not any(not self.validate(source) for source in
                       ("topcv", "vietnamworks", "careerviet", "vieclam24h", "itviec",
                        "joboko", "jobsgo"))

    def validate(self, source="topcv") -> list:
        """Trả về danh sách lỗi cấu hình (rỗng = hợp lệ)."""
        errs = []
        if source == "vietnamworks":
            if not self.vietnamworks_email.strip():
                errs.append("Chưa nhập Email đăng nhập VietnamWorks.")
            if not self.vietnamworks_password:
                errs.append("Chưa nhập Mật khẩu VietnamWorks.")
        elif source == "careerviet":
            if not self.careerviet_email.strip():
                errs.append("Chưa nhập Email đăng nhập CareerViet.")
            if not self.careerviet_password:
                errs.append("Chưa nhập Mật khẩu CareerViet.")
        elif source == "vieclam24h":
            if not self.vieclam24h_email.strip():
                errs.append("Chưa nhập Email đăng nhập Việc Làm 24h.")
            if not self.vieclam24h_password:
                errs.append("Chưa nhập Mật khẩu Việc Làm 24h.")
        elif source == "itviec":
            if not self.itviec_email.strip():
                errs.append("Chưa nhập Email đăng nhập ITViec.")
            if not self.itviec_password:
                errs.append("Chưa nhập Mật khẩu ITViec.")
        elif source == "joboko":
            if not self.joboko_email.strip():
                errs.append("Chưa nhập Email đăng nhập Joboko.")
            if not self.joboko_password:
                errs.append("Chưa nhập Mật khẩu Joboko.")
        elif source == "jobsgo":
            if not self.jobsgo_email.strip():
                errs.append("Chưa nhập Email đăng nhập JobsGO.")
            if not self.jobsgo_password:
                errs.append("Chưa nhập Mật khẩu JobsGO.")
        else:
            if not self.email.strip():
                errs.append("Chưa nhập Email đăng nhập TopCV.")
            if not self.password:
                errs.append("Chưa nhập Mật khẩu TopCV.")
        if not self.cv_folder.strip():
            errs.append("Chưa chọn thư mục lưu CV.")
        if not self.db_path.strip():
            errs.append("Chưa chọn nơi lưu cơ sở dữ liệu.")
        if not (1 <= int(self.concurrency) <= 8):
            errs.append("Số CV tải cùng lúc phải từ 1 đến 8.")
        return errs
