# -*- coding: utf-8 -*-
"""
Nguồn Việc Làm 24h (ntd.vieclam24h.vn) - tải CV ứng viên từ trang nhà tuyển dụng.

Cách hoạt động:
  1. Dùng Chrome đăng nhập MỘT LẦN (profile riêng, lần sau còn phiên).
  2. Lấy JWT `re_access_token` từ cookie mà trang web đang dùng.
  3. Gọi API REST `apiv2.vieclam24h.vn` để lấy danh sách hồ sơ ứng tuyển.
  4. File CV nằm trên CDN công khai `cdn1.vieclam24h.vn`, tải trực tiếp không cần auth.
  5. Token hết hạn → đăng nhập lại tự động, người dùng không phải làm gì.
"""
import json
import math
import random
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import requests

from .base import Provider, LoginError
from ..config import account_for_source
from .topcv import sniff_ext, response_ext
from ..browser import start_driver, safe_get, bring_to_front, ChromeStartError, browser_fetch_bytes
from .. import net

WEB = "https://ntd.vieclam24h.vn"
API = "https://apiv2.vieclam24h.vn"
CDN = "https://cdn1.vieclam24h.vn"
LOGIN_URL = f"{WEB}/taikhoan/login_ntd"
MANAGER_URL = f"{WEB}/nha-tuyen-dung/quan-tri/ntd-trang-quan-tri-ho-so-ung-tuyen.html"
LIST_API = f"{API}/mix/fe/employer/resume-applied-history"
STATISTIC_API = f"{API}/mix/fe/employer/resume-applied-history/statistic"
TOKEN_COOKIE = "re_access_token"
PAGE_SIZE = 20

# Múi giờ Việt Nam
VN_TZ = timezone(timedelta(hours=7))


class Vieclam24hProvider(Provider):
    key = "vieclam24h"
    display_name = "Việc Làm 24h"
    website = "ntd.vieclam24h.vn"
    available = True
    max_concurrency = 4

    def __init__(self, cfg, log=print):
        super().__init__(cfg, log)
        self.driver = None
        self.run_mode = "moi"
        self._token = ""
        self._cookies = {}
        self._ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")
        self._total = 0
        self._last_page = 0
        self._first_page = []
        #: {province_id: tên tỉnh} lấy từ __NEXT_DATA__ của trang quản trị -
        #: API danh sách chỉ trả province_id dạng SỐ, không có tên.
        self._province_map = {}
        self._local = threading.local()
        self._lock = threading.Lock()
        self._driver_lock = threading.RLock()
        self._throttle_lock = threading.Lock()
        self._next_request_at = 0.0

    # ---- hiệu năng ----
    def concurrency_limit(self):
        return 2 if self.run_mode in ("tatca", "loi") else 4

    def minimum_item_delay_ms(self):
        return 600 if self.run_mode in ("tatca", "loi") else 250

    def minimum_page_delay_ms(self):
        return 800 if self.run_mode in ("tatca", "loi") else 350

    def _request_interval(self):
        return 0.25 if self.run_mode in ("tatca", "loi") else 0.08

    # ---- trình duyệt ----
    def _browser_cfg(self):
        return SimpleNamespace(
            headless=getattr(self.cfg, "headless", False),
            chrome_version=getattr(self.cfg, "chrome_version", 0),
            chromedriver_path=getattr(self.cfg, "chromedriver_path", ""),
            proxy_url=getattr(self.cfg, "proxy_url", ""),
            profile_dir=self.cfg.vieclam24h_profile_dir,
        )

    # ---- phiên làm việc ----
    def _read_session(self):
        """Đọc cookie và token từ Chrome browser."""
        with self._driver_lock:
            self._cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
            self._ua = self.driver.execute_script("return navigator.userAgent") or self._ua
        token = self._cookies.get(TOKEN_COOKIE, "")
        if token:
            self._token = token
            self._local = threading.local()
            return True
        return False

    def _session(self):
        """Lấy hoặc tạo requests.Session cho luồng hiện tại, đồng bộ token."""
        session = getattr(self._local, "session", None)
        if session is None or getattr(self._local, "token", None) != self._token:
            session = requests.Session()
            net.apply(session, self.cfg)
            session.headers.update({
                "User-Agent": self._ua,
                "Accept": "application/json, text/plain, */*",
                "Referer": MANAGER_URL,
                "Authorization": f"Bearer {self._token}",
            })
            for name, value in self._cookies.items():
                session.cookies.set(name, value, domain="ntd.vieclam24h.vn")
            self._local.session = session
            self._local.token = self._token
        return session

    def _refresh_session(self, rejected_token=""):
        """Làm mới phiên từ Chrome khi token hết hạn."""
        with self._lock:
            if rejected_token and self._token and self._token != rejected_token:
                return True
            safe_get(self.driver, MANAGER_URL, 0.5)
            time.sleep(2)
            if self._read_session():
                if not rejected_token or self._token != rejected_token:
                    return True
            # Thử đăng nhập lại bằng form
            self._do_login()
            return self._read_session() and (not rejected_token or self._token != rejected_token)

    def _do_login(self):
        """Điền form đăng nhập trên Chrome."""
        email = getattr(self.cfg, "vieclam24h_email", "")
        password = getattr(self.cfg, "vieclam24h_password", "")
        if not email or not password:
            raise LoginError("Chưa cấu hình tài khoản Việc Làm 24h. Vào tab Cấu hình để nhập email và mật khẩu.")
        safe_get(self.driver, LOGIN_URL, 1)
        time.sleep(3)
        try:
            with self._driver_lock:
                cur_url = self.driver.current_url
                self.log(f"[VL24h debug] Trang hiện tại: {cur_url}")
                page_src_snippet = self.driver.page_source[:500] if self.driver.page_source else ""
                self.log(f"[VL24h debug] Snippet HTML: {page_src_snippet[:200]}")

                # Thử nhiều cách tìm input email
                email_input = None
                for by, sel in [
                    ("name", "email"),
                    ("name", "username"),
                    ("css selector", "input[type='email']"),
                    ("css selector", "input[name='email']"),
                    ("css selector", "input[placeholder*='email' i]"),
                    ("css selector", "input[placeholder*='tài khoản' i]"),
                    ("css selector", "input[placeholder*='Email' i]"),
                ]:
                    try:
                        el = self.driver.find_element(by, sel)
                        if el.is_displayed():
                            email_input = el
                            self.log(f"[VL24h debug] Tìm thấy email field: by={by} sel={sel}")
                            break
                    except Exception:
                        pass

                if email_input is None:
                    # Chụp snapshot HTML để debug
                    html_snippet = self.driver.page_source[:2000] if self.driver.page_source else "(trống)"
                    self.log(f"[VL24h debug] Không tìm thấy email input. HTML: {html_snippet[:500]}")
                    raise LoginError("Không tìm thấy trường email trong form đăng nhập Việc Làm 24h")

                email_input.clear()
                email_input.send_keys(email)

                # Thử nhiều cách tìm input mật khẩu
                pwd_input = None
                for by, sel in [
                    ("name", "password"),
                    ("css selector", "input[type='password']"),
                    ("css selector", "input[name='password']"),
                    ("css selector", "input[placeholder*='mật khẩu' i]"),
                    ("css selector", "input[placeholder*='Password' i]"),
                ]:
                    try:
                        el = self.driver.find_element(by, sel)
                        if el.is_displayed():
                            pwd_input = el
                            self.log(f"[VL24h debug] Tìm thấy password field: by={by} sel={sel}")
                            break
                    except Exception:
                        pass

                if pwd_input is None:
                    raise LoginError("Không tìm thấy trường mật khẩu trong form đăng nhập Việc Làm 24h")

                pwd_input.clear()
                pwd_input.send_keys(password)

                # Tìm nút submit
                submit_btn = None
                for by, sel in [
                    ("css selector", "button[type='submit']"),
                    ("css selector", "input[type='submit']"),
                    ("css selector", "button.btn-login"),
                    ("css selector", "button.login-btn"),
                    ("css selector", ".btn-login"),
                    ("xpath", "//button[contains(text(),'Đăng nhập')]"),
                    ("xpath", "//button[contains(text(),'Login')]"),
                    ("xpath", "//input[@type='submit']"),
                ]:
                    try:
                        el = self.driver.find_element(by, sel)
                        if el.is_displayed():
                            submit_btn = el
                            self.log(f"[VL24h debug] Tìm thấy submit button: by={by} sel={sel}")
                            break
                    except Exception:
                        pass

                if submit_btn:
                    submit_btn.click()
                    self.log("[VL24h debug] Đã click nút đăng nhập")
                else:
                    # Thử submit bằng Enter
                    from selenium.webdriver.common.keys import Keys
                    pwd_input.send_keys(Keys.RETURN)
                    self.log("[VL24h debug] Đã nhấn Enter để đăng nhập")
        except LoginError:
            raise
        except Exception as exc:
            raise LoginError(f"Không tìm thấy form đăng nhập Việc Làm 24h: {str(exc)[:200]}")
        time.sleep(4)

    def _wait_login(self, minutes=5):
        """Chờ người dùng đăng nhập thủ công trên Chrome (captcha/OTP)."""
        bring_to_front(self.driver)
        self.log("Việc Làm 24h cần đăng nhập/xác minh trên Chrome; phần mềm sẽ tự chạy tiếp ngay khi thành công.")
        deadline = time.time() + minutes * 60
        check_count = 0
        while time.time() < deadline:
            try:
                check_count += 1
                with self._driver_lock:
                    current_url = self.driver.current_url.lower()
                # Log every 15 checks (30s)
                if check_count % 15 == 1:
                    self.log(f"[VL24h debug] Đang chờ đăng nhập... URL: {current_url}")
                    # Thử đọc all cookies để debug
                    all_cookies = {c['name']: c['value'][:20] for c in self.driver.get_cookies()}
                    self.log(f"[VL24h debug] Cookies hiện tại: {list(all_cookies.keys())}")

                if self._read_session():
                    self.log("Đã phát hiện phiên đăng nhập Việc Làm 24h mới!")
                    return

                # Nếu đã rời khỏi trang login (không còn 'login' hay 'taikhoan' trong URL)
                # nhưng chưa có token → trang có thể đang chuyển hướng
                if "login" not in current_url and "taikhoan" not in current_url:
                    time.sleep(2)
                    if self._read_session():
                        self.log("Đã phát hiện phiên đăng nhập Việc Làm 24h mới!")
                        return
            except Exception:
                pass
            time.sleep(2)
        raise LoginError("Hết thời gian chờ đăng nhập Việc Làm 24h. Hãy hoàn tất đăng nhập trên Chrome rồi thử lại.")

    # ---- gọi mạng ----
    def _wait_throttle(self):
        with self._throttle_lock:
            now = time.monotonic()
            ready = self._next_request_at
            interval = self.jitter_delay(self._request_interval(), self.request_jitter_ratio)
            self._next_request_at = max(now, ready) + interval
        if ready > now:
            time.sleep(min(ready - now, 60))

    def _request(self, method, url, **kwargs):
        """Gọi API có retry, refresh token và backoff."""
        last = None
        timeout = kwargs.pop("timeout", 90)
        for attempt in range(4):
            self._wait_throttle()
            request_token = self._token
            try:
                response = self._session().request(method, url, timeout=timeout, **kwargs)
                last = response
            except requests.RequestException as exc:
                if attempt == 3:
                    raise RuntimeError(f"Lỗi kết nối Việc Làm 24h: {str(exc)[:120]}")
                time.sleep(2 ** attempt)
                continue
            if response.status_code == 401:
                if attempt < 3 and self._refresh_session(request_token):
                    continue
                raise LoginError("Phiên Việc Làm 24h đã hết hạn. Hãy đăng nhập lại trên Chrome rồi tiếp tục.")
            if response.status_code in (408, 429, 502, 503, 504) and attempt < 3:
                delay = self._retry_delay(response, attempt)
                self.log(f"Việc Làm 24h tạm bận (HTTP {response.status_code}), thử lại sau {delay} giây...")
                with self._throttle_lock:
                    self._next_request_at = max(self._next_request_at, time.monotonic() + delay)
                time.sleep(delay)
                continue
            return response
        return last

    @staticmethod
    def _retry_delay(response, attempt):
        try:
            retry_after = float(response.headers.get("Retry-After") or 0)
        except (TypeError, ValueError):
            retry_after = 0
        if retry_after > 0:
            return min(60, retry_after)
        return min(30, 2 ** (attempt + 1) + random.uniform(0.25, 1.0))

    # ---- kết nối ----
    def connect(self):
        try:
            if self.driver is None:
                self.log("Đang khởi động Chrome cho Việc Làm 24h...")
                self.driver = start_driver(self._browser_cfg())
                self.log("Chrome Việc Làm 24h đã sẵn sàng. Đang kiểm tra phiên đăng nhập...")

            # Mở trang quản trị để lấy cookie phiên
            safe_get(self.driver, MANAGER_URL, 0.5)
            time.sleep(2)

            if not self._read_session():
                # Chưa có phiên → thử đăng nhập tự động
                self.log("Chưa thấy phiên đăng nhập Việc Làm 24h, đang thử đăng nhập tự động...")
                try:
                    self._do_login()
                    time.sleep(2)
                except Exception as exc:
                    self.log(f"Đăng nhập tự động không thành công: {exc}")
                if not self._read_session():
                    # Có thể cần captcha/OTP → chờ người dùng
                    self._wait_login()

            # Kiểm tra token bằng cách gọi API thống kê
            response = self._request("GET", STATISTIC_API)
            if response.status_code != 200:
                raise LoginError(f"Không đọc được dữ liệu Việc Làm 24h (HTTP {response.status_code}). "
                                 "Hãy kiểm tra lại Email/Mật khẩu hoặc xác minh trên Chrome.")

            self._load_province_map()

            # Lấy trang đầu tiên
            page_items, metadata = self._fetch_page(1)
            self._first_page = page_items
            self._total = int(metadata.get("total_items") or len(page_items))
            self._last_page = int(metadata.get("total_pages") or math.ceil(self._total / PAGE_SIZE) or 1)
            self.log(f"Việc Làm 24h: tìm thấy {self._total:,} lượt ứng tuyển trên {self._last_page:,} trang.")
        except (LoginError, ChromeStartError):
            raise
        except Exception as exc:
            import traceback
            self.log(f"Lỗi khi kết nối Việc Làm 24h: {exc}\n{traceback.format_exc()}")
            raise LoginError(f"Lỗi kết nối Việc Làm 24h: {str(exc)[:150]}")

    # ---- dữ liệu ----
    def _fetch_page(self, page):
        """Lấy một trang danh sách hồ sơ ứng tuyển."""
        params = {
            "page": int(page),
            "per_page": PAGE_SIZE,
            "status": 1,
            "includes": "employer_note_resume_applied,tags,resume_info",
        }
        response = self._request("GET", LIST_API, params=params)
        try:
            body = response.json() if response.status_code == 200 else None
        except ValueError:
            body = None
        if body is None or body.get("code") != 200:
            raise RuntimeError(f"Việc Làm 24h trả về HTTP {response.status_code} khi đọc trang {page}")
        data = body.get("data") or {}
        items = data.get("items") or []
        return [self._normalize(row) for row in items], data

    @staticmethod
    def _timestamp_from_unix(ts):
        """Chuyển Unix timestamp sang chuỗi datetime Việt Nam."""
        if not ts:
            return ""
        try:
            dt = datetime.fromtimestamp(int(ts), tz=VN_TZ)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, OSError):
            return ""

    @staticmethod
    def _display_date(ts):
        """Chuyển Unix timestamp sang dạng hiển thị dd/mm/yyyy HH:MM."""
        if not ts:
            return ""
        try:
            dt = datetime.fromtimestamp(int(ts), tz=VN_TZ)
            return dt.strftime("%d/%m/%Y %H:%M")
        except (ValueError, TypeError, OSError):
            return ""

    @staticmethod
    def _birth_year(ts):
        """Trích năm sinh từ Unix timestamp."""
        if not ts:
            return ""
        try:
            return str(datetime.fromtimestamp(int(ts), tz=VN_TZ).year)
        except (ValueError, TypeError, OSError):
            return ""

    @staticmethod
    def _gender(code):
        """Chuyển mã giới tính sang chuỗi hiển thị."""
        mapping = {1: "Nữ", 2: "Nam"}
        return mapping.get(code, "")

    #: Enum tình trạng hôn nhân của Vieclam24h (API trả mã số).
    _MARITAL_MAP = {1: "Độc thân", 2: "Đã kết hôn", 3: "Khác"}

    def _load_province_map(self):
        """Lấy {province_id: tên} từ mảng `provinces` trong __NEXT_DATA__ của
        trang quản trị. Best-effort - nếu không lấy được thì `desired_location`
        để trống thay vì hiện mã số.

        Chủ động mở lại `MANAGER_URL` và chờ __NEXT_DATA__ có mặt: sau bước đăng
        nhập trình duyệt có thể đang ở trang khác, và __NEXT_DATA__ (Next.js SSR)
        nằm trong HTML đầu tiên nên không cần chờ render, chỉ cần đúng trang."""
        data = None
        deadline = time.time() + 15
        while time.time() < deadline and data is None:
            try:
                with self._driver_lock:
                    html = self.driver.page_source or ""
                    if "__NEXT_DATA__" not in html or '"provinces"' not in html:
                        safe_get(self.driver, MANAGER_URL, 1.0)
                        html = self.driver.page_source or ""
                match = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
                if match:
                    parsed = json.loads(match.group(1))
                    if '"provinces"' in html:
                        data = parsed
            except Exception:                            # noqa: BLE001
                pass
            if data is None:
                time.sleep(1)
        if data is None:
            return

        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("provinces"), list):
                    for prov in node["provinces"]:
                        if isinstance(prov, dict) and prov.get("id") and prov.get("name"):
                            self._province_map[int(prov["id"])] = str(prov["name"]).strip()
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(data)

    def _resolve_desired_location(self, row):
        """`row["desired_location"]` là DANH SÁCH province_id (số). Đổi sang tên
        rồi chuẩn hoá về tên tỉnh/thành chuẩn (Vieclam24h ghi "TP.HCM"...)."""
        ids = row.get("desired_location")
        if not isinstance(ids, list) or not self._province_map:
            return ""
        names = [self._province_map.get(int(x)) for x in ids
                 if isinstance(x, (int, float)) or str(x).isdigit()]
        joined = ", ".join(dict.fromkeys(n for n in names if n))
        from ..geo import normalize_location
        return normalize_location(joined)

    def _normalize(self, row):
        """Chuẩn hóa một bản ghi từ API Vieclam24h sang schema chung."""
        seeker = row.get("seeker_info") or {}
        job = row.get("job_info") or {}
        resume = row.get("resume_info") or {}
        note_obj = row.get("employer_note_resume_applied")

        applied_ts = self._timestamp_from_unix(row.get("applied_at"))
        applied_at = self._display_date(row.get("applied_at"))

        # URL tải CV: ghép CDN + đường dẫn file
        file_path = row.get("file") or row.get("file_name") or ""
        cv_url = f"{CDN}{file_path}" if file_path else ""

        # Nhãn tags
        tags = row.get("tags") or []
        labels = ", ".join(str(t.get("name") or t) for t in tags if isinstance(t, dict)) if tags else ""

        return {
            "source": self.key,
            "account": account_for_source(self.cfg, self.key),
            "cv_id": str(row.get("id") or ""),
            "fullname": seeker.get("name") or "",
            "email": seeker.get("email") or "",
            "phone": seeker.get("mobile") or "",
            "position": job.get("title") or resume.get("title") or "",
            "campaign_id": str(row.get("job_id") or ""),
            "applied_at": applied_at,
            "applied_ts": applied_ts,
            "apply_source": row.get("created_source") or "Việc Làm 24h",
            "status": self._recruitment_status(row.get("recruitment_status")),
            "gender": self._gender(seeker.get("gender")),
            "birth_year": self._birth_year(seeker.get("birthday")),
            "marital_status": self._MARITAL_MAP.get(seeker.get("marital_status"), ""),
            "experience": str(resume.get("experience") or ""),
            "address": seeker.get("address") or "",
            "city": "",  # Chỉ có province_id, không có tên tỉnh trong response
            # "Địa điểm làm việc mong muốn" = danh sách province_id, giải mã sang
            # tên bằng bảng tra lấy từ __NEXT_DATA__ trang quản trị.
            "desired_location": self._resolve_desired_location(row),
            "last_company": "",
            "labels": labels,
            "note": (note_obj.get("note") or "") if isinstance(note_obj, dict) else "",
            "is_viewed": 1 if row.get("view_resume") == 1 else 0,
            "cv_url": cv_url,
            "candidate_id": str(seeker.get("id") or ""),
            "resume_id": str(row.get("resume_id") or ""),
            "current_title": resume.get("title") or "",
            "profile_type": str(row.get("resume_type") or ""),
            "source_payload": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            "_file_path": file_path,
        }

    @staticmethod
    def _recruitment_status(code):
        """Chuỗi trạng thái tuyển dụng từ mã số."""
        mapping = {
            0: "Chưa xử lý",
            1: "Đã xem",
            2: "Đang liên hệ",
            3: "Phỏng vấn",
            4: "Đạt yêu cầu",
            5: "Không đạt",
            6: "Nhận việc",
            7: "Từ chối",
            8: "Đã liên hệ",
        }
        return mapping.get(code, str(code) if code else "")

    def total_count(self):
        return self._total

    @property
    def last_page(self):
        return self._last_page

    def range_total(self, start_page=1, end_page=None):
        end_page = min(int(end_page or self._last_page), self._last_page)
        start_page = max(1, int(start_page))
        if start_page > end_page:
            return 0
        before = (start_page - 1) * PAGE_SIZE
        return max(0, min(self._total, end_page * PAGE_SIZE) - before)

    def peek_first_page(self):
        return self._first_page

    def iter_pages(self, start_page=1, end_page=None, reverse=False):
        end_page = min(int(end_page or self._last_page), self._last_page)
        pages = list(range(max(1, int(start_page)), end_page + 1))
        if reverse:
            pages.reverse()
        for page in pages:
            if page == 1:
                items, metadata = self._first_page, {"total_pages": self._last_page}
            else:
                items, metadata = self._fetch_page(page)
            if not items:
                current_last = int(metadata.get("total_pages") or self._last_page)
                if page <= min(end_page, current_last):
                    raise RuntimeError(
                        f"Việc Làm 24h trả về trang {page} rỗng bất thường; giữ checkpoint để thử lại.")
                return
            yield page, items

    # ---- tải file CV ----
    def download(self, item_or_id):
        """Tải file CV từ CDN Vieclam24h.

        File nằm trên CDN công khai nên tải trực tiếp bằng HTTP GET, không cần
        Bearer token hay cookie xác thực.
        """
        item = item_or_id if isinstance(item_or_id, dict) else {"cv_id": str(item_or_id)}

        file_path = item.get("_file_path") or item.get("cv_url", "")
        if not file_path:
            return None, "Hồ sơ không có file CV đính kèm"

        # Nếu file_path là URL đầy đủ thì dùng luôn, nếu là path tương đối thì ghép CDN
        if file_path.startswith("http"):
            url = file_path
        elif file_path.startswith("/"):
            url = f"{CDN}{file_path}"
        else:
            url = f"{CDN}/{file_path}"

        http_error = None
        try:
            self._wait_throttle()
            # Tải từ CDN công khai, không cần token
            response = requests.get(url, timeout=120, headers={"User-Agent": self._ua},
                                    **net.request_kwargs(self.cfg))
            if response.status_code == 200 and response.content:
                ext = sniff_ext(response.content) or response_ext(response)
                if ext:
                    return response.content, ext
                http_error = "nội dung CDN không phải file CV hợp lệ"
            else:
                http_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            http_error = f"lỗi kết nối CDN ({str(exc)[:100]})"

        # Dự phòng: tải lại NGAY TRONG Chrome đã đăng nhập - mạng công ty hay chặn
        # riêng CDN, còn trình duyệt thì dùng đúng proxy hệ thống nên vẫn tải được.
        status, data = browser_fetch_bytes(
            self.driver, self._driver_lock, "GET", url, credentials="omit")
        if data:
            ext = sniff_ext(data)
            if ext:
                return data, ext
        return None, f"Không tải được CV từ Việc Làm 24h: {http_error or ('HTTP ' + str(status or 0))}"

    # ---- dọn dẹp ----
    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
