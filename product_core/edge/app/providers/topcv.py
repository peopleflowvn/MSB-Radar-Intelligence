# -*- coding: utf-8 -*-
"""
Nguồn TopCV (tuyendung.topcv.vn) - đã hỗ trợ đầy đủ.

Cách hoạt động:
  1. Dùng Chrome đăng nhập MỘT LẦN (profile riêng nên lần sau còn phiên, khỏi đăng nhập lại).
  2. Lấy access token mà chính trang web TopCV đang dùng.
  3. Gọi đúng địa chỉ mà nút "..." → "Tải CV" trên giao diện TopCV gọi:
         GET /api/v1/cv-management/download-cv?id=<mã CV>
     nên kết quả giống hệt bấm tay, nhưng nhanh và ổn định hơn nhiều.
  4. Token hết hạn sau ~1 giờ → tự lấy lại, người dùng không phải làm gì.
"""
import base64
import json
import os
import random
import re
import threading
import time

import requests
import urllib3

from ..browser import start_driver, safe_get, close_popups, bring_to_front
from .base import Provider, LoginError
from ..config import account_for_source
from .. import net

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API = "https://tuyendung-api.topcv.vn/api/v1"
WEB = "https://tuyendung.topcv.vn"
LOGIN_URL = f"{WEB}/app/login"
CVS_URL = f"{WEB}/app/cvs-management"
TOKEN_KEY = "local_storage__token.refresh"
TOKEN_EXP_KEY = "local_storage__token_expiration.refresh"

_MAGIC = [(b"%PDF", ".pdf"), (b"PK\x03\x04", ".docx"), (b"\xd0\xcf\x11\xe0", ".doc"),
          (b"{\\rtf", ".rtf"), (b"\x89PNG", ".png"), (b"\xff\xd8\xff", ".jpg")]


def sniff_ext(data: bytes):
    """Đoán đuôi file từ nội dung, cho phép BOM/phần đệm trước header thật."""
    head = (data or b"")[:4096].lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
    for magic, ext in _MAGIC:
        # PDF cho phép header xuất hiện trong 1024 byte đầu; file do một số hệ
        # thống trung gian tạo cũng có BOM/phần đệm trước magic bytes.
        pos = head.find(magic)
        if 0 <= pos <= 1024:
            return ext
    return None


def response_ext(response):
    """Dự phòng theo Content-Type/Content-Disposition khi file không có magic chuẩn."""
    content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
    by_type = {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/rtf": ".rtf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
    }
    if content_type in by_type:
        return by_type[content_type]
    disposition = response.headers.get("Content-Disposition") or ""
    match = re.search(r"filename\*?=(?:UTF-8''|[\"']?)([^\"';]+)", disposition, re.I)
    if match:
        ext = os.path.splitext(match.group(1).strip())[1].lower()
        if ext in {x[1] for x in _MAGIC}:
            return ext
    return None


class TopCVProvider(Provider):
    key = "topcv"
    display_name = "TopCV"
    website = "tuyendung.topcv.vn"
    available = True
    #: Cho engine tự mở chi tiết bổ sung "Sẵn sàng di chuyển (địa điểm)" =
    #: nơi làm việc mong muốn cho hồ sơ cũ khi chạy "Tải tất cả". Xem
    #: KINH_NGHIEM_TRIEN_KHAI_CAC_KENH_TUYEN_DUNG.md mục 41.
    supports_detail_enrichment = True

    def __init__(self, cfg, log=print):
        super().__init__(cfg, log)
        self.driver = None
        self._token = None
        self._token_exp = 0
        self._lock = threading.Lock()
        self._driver_lock = threading.Lock()   # Chrome chỉ dùng được từ 1 luồng 1 lúc
        self._throttle_lock = threading.Lock()
        self._throttle_until = 0.0
        self._next_request_at = 0.0
        self._transient_failures = 0
        self.run_mode = "moi"
        self._local = threading.local()
        self._ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")
        self._cookies = {}
        self._first_page = None
        self._first_page_items = []
        self._last_page = 1
        self._total = 0

    def concurrency_limit(self):
        return 2 if self.run_mode in ("tatca", "loi") else 4

    def minimum_item_delay_ms(self):
        return 600 if self.run_mode in ("tatca", "loi") else 250

    def minimum_page_delay_ms(self):
        return 800 if self.run_mode in ("tatca", "loi") else 350

    def _request_interval(self):
        return 0.25 if self.run_mode in ("tatca", "loi") else 0.08

    # ---------------- đăng nhập ----------------
    def _fill_login_form(self, submit=True):
        """Điền sẵn Email/Mật khẩu vào trang đăng nhập TopCV.

        Tách riêng khỏi _do_login() để dùng lại được cả khi phải nhờ người dùng xác minh:
        phần mềm điền hộ tài khoản, người dùng chỉ còn việc giải captcha rồi bấm Đăng
        nhập - đỡ phải gõ lại email/mật khẩu dài bằng tay mỗi lần.

        Trả về True nếu điền được, False nếu không tìm thấy ô nhập (trang chưa dựng xong).
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            email_el = WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//input[@type='email' or contains(@placeholder,'Email')]")))
        except Exception:
            return False

        try:
            email_el.click()
            email_el.clear()
            for ch in self.cfg.email:
                email_el.send_keys(ch)
                time.sleep(random.uniform(0.02, 0.07))
            pwd_el = self.driver.find_element(By.XPATH, "//input[@type='password']")
            pwd_el.click()
            pwd_el.clear()
            for ch in self.cfg.password:
                pwd_el.send_keys(ch)
                time.sleep(random.uniform(0.02, 0.07))
            time.sleep(random.uniform(0.4, 0.9))
            if submit:
                pwd_el.send_keys(Keys.ENTER)
            return True
        except Exception:
            return False

    def _do_login(self):
        from selenium.webdriver.support.ui import WebDriverWait

        self.log("Phiên đăng nhập đã hết hạn, đang đăng nhập lại...")
        safe_get(self.driver, LOGIN_URL, 2.5)
        if "/app/login" not in self.driver.current_url:
            return True
        if not self._fill_login_form(submit=True):
            raise LoginError("Không tìm thấy ô nhập Email trên trang đăng nhập TopCV.")
        try:
            WebDriverWait(self.driver, 25).until(lambda d: "/app/login" not in d.current_url)
        except Exception:
            pass
        time.sleep(2)

        # Vẫn nằm ở trang đăng nhập = TopCV chưa chấp nhận, gần như luôn là do đang hỏi
        # captcha/OTP. KHÔNG báo lỗi ngay ở đây: việc đó chỉ khiến người dùng thấy phần
        # mềm "thất bại" trong khi thực ra chỉ cần họ xác minh một cái là xong. Trả về
        # False để tầng gọi chuyển sang chế độ CHỜ NGƯỜI DÙNG xác minh bằng tay.
        return "/app/login" not in self.driver.current_url

    def _clear_stale_token(self):
        """Xoá token đã hết hạn khỏi localStorage trước khi nhờ người dùng đăng nhập lại.

        RẤT QUAN TRỌNG: TopCV KHÔNG tự xoá token cũ khi phiên hết hạn - nó vẫn nằm
        nguyên trong localStorage. Nếu không xoá, hàm chờ người dùng sẽ đọc lại đúng
        token hỏng đó ngay lập tức và tưởng nhầm là "đã đăng nhập xong", trong khi
        người dùng còn chưa kịp chạm vào bàn phím. Xoá đi thì chỉ khi nào đăng nhập
        thật sự thành công mới có token mới xuất hiện - lúc đó mới là tín hiệu đúng.
        """
        try:
            self.driver.execute_script(
                f"localStorage.removeItem('{TOKEN_KEY}');"
                f"localStorage.removeItem('{TOKEN_EXP_KEY}');")
        except Exception:
            pass

    # ---------------- chờ người dùng tự xác minh ----------------
    def _wait_for_human(self, minutes=5, reject_token=None):
        """Nhường quyền cho người dùng khi TopCV đòi xác minh (captcha/OTP/thiết bị lạ).

        Phần mềm KHÔNG tìm cách tự vượt xác minh - đó là việc của con người. Nhiệm vụ ở
        đây chỉ là: đưa cửa sổ Chrome ra trước mặt, báo cho người dùng biết, rồi kiên
        nhẫn chờ. Xác minh xong, phiên được lưu vào profile Chrome nên các lần chạy sau
        (kể cả chạy tự động theo lịch) sẽ không phải làm lại.
        """
        # Nếu phiên đã hợp lệ thì chạy tiếp ngay, không hiện thông báo và không chờ.
        tok, exp = self._read_token()
        if tok and tok != reject_token:
            return tok, exp

        if getattr(self.cfg, "headless", False):
            raise LoginError(
                "TopCV đang yêu cầu xác minh (captcha/OTP) nhưng phần mềm đang chạy ở "
                "chế độ ẩn cửa sổ Chrome nên bạn không thao tác được.\n\n"
                "Hãy vào tab Cấu hình, BỎ CHỌN 'Ẩn cửa sổ Chrome' rồi chạy lại.")

        # Chỉ xóa token khi biết chắc đó là token cũ vừa bị máy chủ từ chối. Ở lần kết
        # nối đầu tiên tuyệt đối không xóa phiên đang đăng nhập sẵn của người dùng.
        if reject_token:
            self._clear_stale_token()
        safe_get(self.driver, LOGIN_URL, 1.5)

        # TopCV tự chuyển khỏi /login nghĩa là cookie đăng nhập còn hiệu lực. Cho trang
        # quản lý CV một nhịp nạp token rồi kiểm tra lại trước khi yêu cầu người dùng.
        if "/app/login" not in self.driver.current_url:
            safe_get(self.driver, CVS_URL, 1.0)
            for _ in range(5):
                tok, exp = self._read_token()
                if tok and tok != reject_token:
                    return tok, exp
                time.sleep(0.4)

        # Điền hộ Email/Mật khẩu (KHÔNG bấm Đăng nhập) để người dùng chỉ còn việc giải
        # captcha rồi bấm nút - không phải gõ lại tài khoản dài dòng bằng tay.
        da_dien = self._fill_login_form(submit=False)

        self.log("╔" + "═" * 60)
        self.log("║ CẦN BẠN ĐĂNG NHẬP TRÊN CỬA SỔ CHROME")
        self.log("║ Cửa sổ Chrome vừa được đưa ra trước mặt (nếu không thấy, nhìn")
        self.log("║ nút Chrome đang nháy trên thanh taskbar).")
        if da_dien:
            self.log("║ Email/Mật khẩu đã được điền sẵn - bạn chỉ cần giải captcha")
            self.log("║ (nếu có) rồi bấm nút ĐĂNG NHẬP.")
        else:
            self.log("║ Hãy đăng nhập và hoàn tất captcha/OTP nếu TopCV hỏi.")
        self.log("║ Phần mềm sẽ TỰ chạy tiếp ngay khi bạn xong - không cần bấm gì thêm.")
        self.log(f"║ (Chờ tối đa {minutes} phút)")
        self.log("╚" + "═" * 60)

        bring_to_front(self.driver)
        try:
            from ..notifier import notify
            notify("MSB Radar Edge - cần bạn đăng nhập",
                   "Hãy đăng nhập TopCV trên cửa sổ Chrome vừa hiện ra. "
                   "Phần mềm sẽ tự chạy tiếp khi xong.")
        except Exception:
            pass

        deadline = time.time() + minutes * 60
        nhac_lai = time.time() + 45
        session_kicked = False
        while time.time() < deadline:
            tok, exp = self._read_token()
            # Chỉ nhận token THẬT SỰ MỚI. Token trùng với token hỏng cũ nghĩa là người
            # dùng chưa đăng nhập xong, không được coi là thành công.
            if tok and tok != reject_token:
                self.log("Đã đăng nhập xong - cảm ơn bạn. Phần mềm chạy tiếp...")
                return tok, exp
            # Sau khi đăng nhập/CAPTCHA thành công, SPA có thể đổi URL trước rồi mới
            # ghi token. Mở trang CV ngay để kích hoạt việc nạp phiên, thay vì chờ mù.
            if "/app/login" not in self.driver.current_url and not session_kicked:
                safe_get(self.driver, CVS_URL, 0.3)
                session_kicked = True
                tok, exp = self._read_token()
                if tok and tok != reject_token:
                    self.log("Đã đăng nhập xong - phần mềm chạy tiếp ngay...")
                    return tok, exp
            elif "/app/login" in self.driver.current_url:
                session_kicked = False
            if time.time() >= nhac_lai:
                con_lai = int((deadline - time.time()) / 60) + 1
                self.log(f"  ... vẫn đang chờ bạn đăng nhập trên Chrome (còn ~{con_lai} phút)")
                bring_to_front(self.driver)
                nhac_lai = time.time() + 45
            time.sleep(2)

        raise LoginError(
            "Hết thời gian chờ bạn xác minh trên cửa sổ Chrome.\n\n"
            "Hãy chạy lại và hoàn tất captcha/OTP trên cửa sổ Chrome hiện ra. "
            "Chỉ cần làm một lần, các lần sau phần mềm sẽ tự nhớ phiên đăng nhập.")

    def _read_token(self):
        """Trang chưa nạp xong thì trình duyệt không cho đọc localStorage -> coi như chưa có."""
        try:
            result = self.driver.execute_script(r"""
                const stores = [window.localStorage, window.sessionStorage];
                const preferred = [
                    'local_storage__token.refresh', 'local_storage__token.access',
                    'access_token', 'token', 'auth._token.local', 'jwt'
                ];
                let token = null, expiration = null;
                for (const store of stores) {
                    if (!store) continue;
                    if (!expiration) expiration = store.getItem('local_storage__token_expiration.refresh')
                        || store.getItem('local_storage__token_expiration.access');
                    for (const key of preferred) {
                        const value = store.getItem(key);
                        if (value && value.length > 20) { token = value; break; }
                    }
                    if (!token) {
                        for (let i = 0; i < store.length; i++) {
                            const key = store.key(i) || '';
                            if (!/token/i.test(key) || /expir|device|firebase/i.test(key)) continue;
                            const value = store.getItem(key);
                            if (value && value.length > 20) { token = value; break; }
                        }
                    }
                    if (token) break;
                }
                return {token, expiration};
            """) or {}
            tok = result.get("token")
            exp = result.get("expiration")
        except Exception:
            return None, 0
        if not tok:
            return None, 0
        # Một số phiên bản SPA lưu token dưới dạng JSON thay vì chuỗi thuần.
        try:
            parsed = json.loads(tok)
            if isinstance(parsed, dict):
                tok = (parsed.get("access_token") or parsed.get("token")
                       or parsed.get("refresh_token") or tok)
            elif isinstance(parsed, str):
                tok = parsed
        except Exception:
            pass
        tok = str(tok).strip().strip('"')
        if not tok.startswith("Bearer"):
            tok = "Bearer " + tok
        try:
            exp_s = float(exp) / 1000.0 if exp else 0
        except Exception:
            exp_s = 0
        return tok, exp_s

    def connect(self):
        if self.driver is None:
            self.log("Đang khởi động Chrome...")
            self.driver = start_driver(self.cfg)
        
        safe_get(self.driver, CVS_URL, 3.0)
        if "/app/login" in self.driver.current_url:
            self._do_login()
            safe_get(self.driver, CVS_URL, 3.0)
        close_popups(self.driver)

        # QUAN TRỌNG: trang TopCV rất hay kẹt ở trạng thái "khung xương" (chỉ hiện các
        # khối xám, giao diện chưa dựng xong) - lúc đó localStorage chưa có token, và
        # KHÔNG BAO GIỜ tự thoát ra được dù chờ bao lâu. Cách duy nhất là MỞ LẠI TRANG.
        # Vì vậy vòng lặp dưới đây phải xen kẽ "chờ" với "mở lại", không được chỉ chờ suông.
        tok, exp = None, 0
        for _ in range(2):
            for _ in range(5):
                tok, exp = self._read_token()
                if tok:
                    break
                time.sleep(0.6)
            if tok:
                break
            self.log("Trang chưa sẵn sàng, đang mở lại...")
            safe_get(self.driver, CVS_URL, 1.0)
            if "/app/login" in self.driver.current_url:
                self._do_login()
                safe_get(self.driver, CVS_URL, 3.0)

        if not tok:
            # Tự làm hết cách rồi vẫn không có phiên -> gần như chắc chắn TopCV đang đòi
            # xác minh. Nhường lại cho người dùng: đưa cửa sổ ra trước, báo, rồi chờ.
            tok, exp = self._wait_for_human()

        self._token, self._token_exp = tok, exp
        try:
            self._ua = self.driver.execute_script("return navigator.userAgent;") or self._ua
            self._cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
        except Exception:
            pass
        self.log("Đã kết nối TopCV thành công.")

        self._first_page = self._fetch_page(1)
        self._total = int(self._first_page.get("total") or 0)
        self._last_page = int(self._first_page.get("last_page") or 1)
        self._first_page_items = [self._normalize(it) for it in (self._first_page.get("data") or [])]

    def _accept_token(self, tok, exp):
        self._token, self._token_exp = tok, exp
        try:
            self._cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
        except Exception:
            pass
        self._local = threading.local()   # buộc tạo lại session HTTP
        self.log("Đã làm mới phiên làm việc.")

    def _refresh_token(self):
        """Lấy lại phiên làm việc mới từ trang web.

        LƯU Ý về điều kiện nhận token: KHÔNG chỉ đòi token phải khác token cũ.
        Khi phiên đã hết hạn hẳn, TopCV không cấp được token mới nữa nên trang chỉ đọc
        lại đúng giá trị cũ; nếu cứ chờ "token phải khác" thì vòng lặp quay đủ 30 lượt
        (~90 giây) rồi trả về mà không báo gì - người dùng chỉ thấy phần mềm đứng im
        rất lâu rồi báo một lỗi khó hiểu ở tận nơi khác. Vì vậy:
          • token MỚI (khác cũ)                -> nhận ngay.
          • token cũ nhưng CÒN HẠN dùng        -> vẫn nhận (hàm gọi đã quá thận trọng).
          • token cũ và ĐÃ HẾT HẠN             -> dừng sớm, báo rõ là phải đăng nhập lại.
        """
        with self._lock:
            before = self._token
            if self.driver is None:
                return
            self.log("Đang làm mới phiên làm việc...")
            for _ in range(3):
                safe_get(self.driver, CVS_URL, 3.0)
                if "/app/login" in self.driver.current_url:
                    self._do_login()
                    safe_get(self.driver, CVS_URL, 3.0)

                stale = False
                for _ in range(10):
                    tok, exp = self._read_token()
                    if tok and tok != before:
                        self._accept_token(tok, exp)
                        return
                    if tok and exp and time.time() < exp - 60:
                        self._accept_token(tok, exp)   # token cũ nhưng vẫn còn hạn
                        return
                    stale = bool(tok)      # đọc được token nhưng là bản cũ đã hết hạn
                    time.sleep(1)

                if stale:
                    # Chờ thêm cũng vô ích: trang không thể tự cấp token mới khi phiên
                    # đã hết hạn. Nhường cho người dùng đăng nhập lại (nếu có cửa sổ
                    # Chrome); hàm dưới tự ném LoginError kèm hướng dẫn nếu không được.
                    tok, exp = self._wait_for_human(reject_token=before)
                    self._accept_token(tok, exp)
                    return

    def _ensure_token(self):
        if not self._token or (self._token_exp and time.time() > self._token_exp - 180):
            self._refresh_token()

    # ---------------- HTTP ----------------
    def _session(self):
        s = getattr(self._local, "s", None)
        if s is None or getattr(self._local, "tok", None) != self._token:
            s = requests.Session()
            # Proxy + chứng chỉ theo chính sách chung (net.py): mặc định vẫn xác
            # thực TLS, nhưng dùng kho chứng chỉ Windows nên proxy soi SSL của
            # công ty không còn làm hỏng lời gọi. Người dùng có thể tắt/đổi CA
            # ở tab Cấu hình khi cần.
            net.apply(s, self.cfg)
            s.headers.update({
                "User-Agent": self._ua, "Authorization": self._token,
                "Referer": WEB + "/", "Origin": WEB,
                "Accept": "application/json, text/plain, */*",
            })
            for k, v in self._cookies.items():
                s.cookies.set(k, v)
            self._local.s = s
            self._local.tok = self._token
        return s

    @staticmethod
    def _retry_delay(response, attempt):
        retry_after = (response.headers.get("Retry-After") or "").strip()
        try:
            return min(60.0, max(0.5, float(retry_after)))
        except (TypeError, ValueError):
            return min(30.0, (2 ** attempt) + random.uniform(0.25, 1.25))

    def _wait_throttle(self):
        """Spread concurrent TopCV requests and honour a shared backoff window."""
        with self._throttle_lock:
            now = time.monotonic()
            ready_at = max(self._throttle_until, self._next_request_at)
            wait = ready_at - now
            interval = self.jitter_delay(
                self._request_interval(), self.request_jitter_ratio)
            self._next_request_at = max(now, ready_at) + interval
        if wait > 0:
            time.sleep(min(wait, 60))

    def _request(self, url, tries=3, timeout=90):
        last = None
        for attempt in range(tries):
            self._wait_throttle()
            self._ensure_token()
            # Chỉ bọc đúng lệnh gọi mạng, để phần xét mã trả về bên dưới luôn chắc chắn
            # có biến `r`. (Bọc cả khối sẽ khiến nhánh bắt lỗi đọc `r` khi request hỏng
            # ngay từ đầu - lúc đó `r` chưa hề tồn tại.)
            try:
                r = self._session().get(url, timeout=timeout)
            except Exception as e:
                last = str(e)[:120]
                time.sleep(2 * (attempt + 1))
                continue

            if r.status_code == 401:
                self._refresh_token()
                continue
            if r.status_code == 403:
                # Gặp 403 (nhà mạng/tường lửa chặn riêng tên miền API) -> thử lại 1 lần,
                # nếu vẫn 403 thì TRẢ VỀ phản hồi đó để tầng gọi bên trên tự chuyển sang
                # gọi lại ngay trong trình duyệt thật (browser fallback).
                last = "HTTP 403"
                if attempt < tries - 1:
                    time.sleep(1.5)
                    continue
                return r
            if r.status_code in (408, 429, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                delay = self._retry_delay(r, attempt)
                with self._throttle_lock:
                    self._transient_failures += 1
                    penalty = min(60.0, delay + max(0, self._transient_failures - 2) * 2)
                    self._throttle_until = max(
                        self._throttle_until, time.monotonic() + penalty)
                time.sleep(delay)
                continue
            with self._throttle_lock:
                self._transient_failures = 0
            return r
        raise RuntimeError(last or "Không gọi được TopCV")

    # ---------------- dự phòng: gọi lại NGAY TRONG trình duyệt ----------------
    # Thư viện requests dùng riêng có thể bị TopCV/tường lửa đối xử khác trình duyệt
    # thật (báo lỗi giả như 422 "CV không còn khả dụng", hoặc bị chặn hẳn ở vài mạng
    # công ty) dù cùng 1 tài khoản, cùng 1 token. Cách chắc ăn nhất để kiểm chứng và
    # khắc phục là gọi LẠI đúng địa chỉ đó nhưng chạy ngay trong tab Chrome đã đăng
    # nhập - giống hệt việc người dùng tự bấm "Tải CV" bằng tay (cùng cookie, cùng
    # User-Agent, cùng "vân tay" mạng của trình duyệt thật). Chỉ dùng khi cách nhanh
    # (requests) đã thất bại, vì cách này chậm hơn nhiều.
    _XHR_SCRIPT = r"""
        var cb = arguments[arguments.length - 1];
        var url = arguments[0], token = arguments[1];
        var xhr = new XMLHttpRequest();
        xhr.open('GET', url, true);
        if (token) xhr.setRequestHeader('Authorization', token);
        xhr.responseType = 'arraybuffer';
        xhr.timeout = 60000;
        xhr.onload = function () {
            var bytes = new Uint8Array(xhr.response || new ArrayBuffer(0));
            var binary = '', CHUNK = 8192;
            for (var i = 0; i < bytes.length; i += CHUNK) {
                binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
            }
            cb({status: xhr.status, data_b64: btoa(binary)});
        };
        xhr.onerror = function () { cb({status: 0, error: 'network error'}); };
        xhr.ontimeout = function () { cb({status: 0, error: 'timeout'}); };
        xhr.send();
        """

    def _browser_fetch(self, url):
        """Gọi `url` từ bên trong trình duyệt thật. Trả về (status_code, bytes) -
        (None, None) nếu không dùng được (chưa có trình duyệt, lỗi thực thi script)."""
        if self.driver is None:
            return None, None
        try:
            with self._driver_lock:
                self.driver.set_script_timeout(65)
                result = self.driver.execute_async_script(
                    self._XHR_SCRIPT, url, self._token)
        except Exception:
            return None, None
        if not result:
            return None, None
        status = result.get("status")
        b64 = result.get("data_b64")
        if not b64:
            return status, None
        try:
            return status, base64.b64decode(b64)
        except Exception:
            return status, None

    def _fetch_page(self, page):
        url = (f"{API}/cv-management/cvs?get_newest_cv=true&keyword="
               f"&filter_cv_pro=false&page={page}")
        api_err = None
        try:
            r = self._request(url)
            if r.status_code == 200:
                return r.json()["cvs"]
            api_err = f"HTTP {r.status_code}"
        except LoginError:
            # Hết phiên đăng nhập thì gọi lại trong trình duyệt cũng vô ích (cùng một
            # phiên đã hỏng). Cho lỗi đi thẳng lên để người dùng nhận đúng hướng dẫn
            # "hãy đăng nhập lại", thay vì bị bọc thành "Lấy danh sách trang 1 lỗi: ...".
            raise
        except Exception as e:
            api_err = str(e)[:200]

        status, data = self._browser_fetch(url)
        if data:
            try:
                import json as _json
                return _json.loads(data.decode("utf-8"))["cvs"]
            except Exception:
                pass
        raise RuntimeError(f"Lấy danh sách trang {page} lỗi: {api_err}")

    # ---------------- Provider ----------------
    def total_count(self):
        return self._total

    @property
    def last_page(self):
        return self._last_page

    def peek_first_page(self):
        return self._first_page_items

    @staticmethod
    def _applied_ts(it):
        """
        Mốc thời gian ỨNG TUYỂN, dùng để sắp xếp và lọc theo ngày.
        KHÔNG dùng 'last_update_time' vì trường đó thay đổi mỗi khi hồ sơ được xem/tải,
        sẽ làm sai bộ lọc theo ngày. Ưu tiên 'created_at_str' (đúng thứ đang hiển thị
        trên TopCV), nếu không có thì lấy 'created_at' (giờ UTC, cộng 7 tiếng).
        """
        s = (it.get("created_at_str") or "").strip()
        if s:
            m = re.match(r"(\d{2})/(\d{2})/(\d{4})[ T]+(\d{2}):(\d{2})", s)
            if m:
                d, mo, y, hh, mi = m.groups()
                return f"{y}-{mo}-{d} {hh}:{mi}:00"
        raw = str(it.get("created_at") or "")
        if raw:
            try:
                from datetime import datetime, timedelta
                dt = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=7)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return raw[:19].replace("T", " ")
        return ""

    def _normalize(self, it):
        camp = it.get("campaign") or {}
        labels = it.get("cv_label") or []
        label_txt = ", ".join(
            str(label.get("name", "")) for label in labels if isinstance(label, dict))
        cid = str(it.get("id"))
        return {
            "source": self.key, "account": account_for_source(self.cfg, self.key), "cv_id": cid,
            "fullname": it.get("fullname") or "", "email": it.get("email") or "",
            "phone": it.get("phone") or "", "position": camp.get("title") or "",
            "campaign_id": str(camp.get("id") or ""),
            "applied_at": it.get("created_at_str") or "",
            "applied_ts": self._applied_ts(it),
            "apply_source": it.get("source_str") or "",
            "status": it.get("status_str") or "",
            "gender": it.get("gender") or "", "birth_year": it.get("year_of_birth") or "",
            "experience": it.get("year_of_experience_str") or "",
            "address": it.get("address") or "", "city": it.get("city_name") or "",
            "last_company": it.get("last_company") or "", "labels": label_txt,
            "note": it.get("note") or "", "is_viewed": 1 if it.get("is_viewed") else 0,
            "cv_url": f"{WEB}/app/cvs-management/cvs/{cid}",
        }

    def iter_pages(self, start_page=1, end_page=None, reverse=False):
        if end_page is None or end_page > self._last_page:
            end_page = self._last_page
        start_page = max(1, start_page)

        pages = list(range(start_page, end_page + 1))
        if reverse:
            pages.reverse()

        for page in pages:
            if page == 1 and self._first_page_items:
                items_norm = self._first_page_items
            else:
                items = self._fetch_page(page).get("data") or []
                if not items:
                    return
                items_norm = [self._normalize(it) for it in items]
            yield page, items_norm

    def _scrape_relocation(self, item):
        """Bóc "Sẵn sàng di chuyển (Địa điểm)" ở sidebar "Thông tin bổ sung từ
        ứng viên" - CHỈ có trên trang chi tiết CV (Vue SPA, phải render qua
        Chrome, `requests` chỉ lấy được khung rỗng). Best-effort: mọi lỗi đều
        nuốt, KHÔNG được làm hỏng đường tải. `detail_loaded` để engine chỉ chạy
        1 lần/hồ sơ."""
        detail_url = item.get("cv_url")
        if not detail_url or self.driver is None:
            item["detail_loaded"] = 1
            return
        text = ""
        try:
            with self._driver_lock:
                safe_get(self.driver, detail_url, 1.5)
                cur = (self.driver.current_url or "")
                if "/app/login" in cur.lower():
                    self.log("  ⓘ TopCV: trang chi tiết CV chuyển về đăng nhập, bỏ qua bóc địa điểm.")
                    item["detail_loaded"] = 1
                    return
                # SPA (Vue) render bất đồng bộ. Chờ tới khi có `.relocation-label`
                # có nội dung, HOẶC hết grace sau khi trang chi tiết đã dựng
                # (mốc: `.campaign-box` hoặc `.cv-preview`/`iframe` khối CV).
                deadline = time.time() + 25
                settled_at = None
                while time.time() < deadline:
                    els = self.driver.find_elements("css selector", ".relocation-label")
                    if els:
                        raw = (els[0].get_attribute("textContent") or "").strip()
                        if raw:
                            text = raw
                            break
                    if settled_at is None and self.driver.find_elements(
                            "css selector", ".campaign-box, .cv-preview, .modal-cv, iframe"):
                        settled_at = time.time()      # trang đã dựng, cho relocation 5s nữa
                    if settled_at and time.time() - settled_at > 5:
                        break
                    time.sleep(0.5)
        except Exception as exc:                         # noqa: BLE001
            self.log(f"  ⓘ TopCV: lỗi khi bóc địa điểm: {str(exc)[:120]}")
            item["detail_loaded"] = 1
            return
        # "Sẵn sàng di chuyển (Hồ Chí Minh)" -> "Hồ Chí Minh"; hoặc chỉ "Hồ Chí Minh"
        match = re.search(r"\(([^)]+)\)", text)
        location = (match.group(1).strip() if match
                    else re.sub(r"(?i)sẵn\s*sàng\s*di\s*chuyển", "", text).strip(" :()"))
        if location:
            from ..geo import normalize_location
            item["desired_location"] = normalize_location(location)
            self.log(f"  ⓘ TopCV: nơi làm việc mong muốn = {item['desired_location']}")
        else:
            self.log("  ⓘ TopCV: trang chi tiết CV không có mục 'Sẵn sàng di chuyển' "
                     f"(text đọc được: {text[:60]!r}).")
        item["detail_loaded"] = 1

    def enrich(self, item):
        """Engine gọi cho hồ sơ cũ (đã tải, chưa detail_loaded) khi "Tải tất cả"."""
        self._scrape_relocation(item)
        return item

    def download(self, item_or_id):
        item = item_or_id if isinstance(item_or_id, dict) else None
        cv_id = (str(item_or_id.get("cv_id")) if isinstance(item_or_id, dict)
                 else str(item_or_id))
        url = f"{API}/cv-management/download-cv?id={cv_id}"

        if item is not None and not item.get("detail_loaded"):
            self._scrape_relocation(item)

        # 1) Cách nhanh: gọi thẳng qua thư viện requests.
        api_err = None
        try:
            r = self._request(url, tries=2)
            if r.status_code == 200 and r.content:
                ext = sniff_ext(r.content) or response_ext(r)
                if ext:
                    return r.content.lstrip(), ext
                content_type = (r.headers.get("Content-Type") or "không rõ").split(";", 1)[0]
                api_err = f"nội dung tải về không phải file CV hợp lệ (Content-Type: {content_type})"
            elif r.status_code == 422:
                api_err = "TopCV báo CV không còn khả dụng"
            else:
                api_err = f"HTTP {r.status_code}"
        except LoginError:
            # Mất phiên giữa chừng: dừng cả tiến trình để người dùng đăng nhập lại,
            # thay vì lặng lẽ đánh dấu HÀNG NGHÌN CV còn lại là "lỗi tải".
            raise
        except Exception as e:
            api_err = str(e)[:180]

        # 2) Dự phòng: thử lại đúng địa chỉ đó NGAY TRONG trình duyệt đã đăng nhập -
        # giống hệt bấm tay "Tải CV". Bắt được các trường hợp API riêng báo lỗi giả
        # (vd 422) mà thực ra CV vẫn tải được bình thường qua giao diện.
        status, data = self._browser_fetch(url)
        if data:
            ext = sniff_ext(data)
            if ext:
                return data.lstrip(), ext
        if status == 422:
            return None, "TopCV báo CV không còn khả dụng (đã kiểm tra lại qua trình duyệt)"
        return None, api_err or (f"HTTP {status}" if status else "Không tải được CV")

    def close(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
