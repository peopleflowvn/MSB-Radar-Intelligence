# -*- coding: utf-8 -*-
"""Provider ITViec: đọc danh sách HTML và tải CV bằng phiên Chrome hợp lệ."""
import math
import random
import re
import threading
import time
from datetime import datetime
from email.message import Message
from types import SimpleNamespace
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .base import Provider, LoginError
from ..browser import ChromeStartError, bring_to_front, safe_get, start_driver, browser_fetch_bytes
from ..config import account_for_source
from .. import net

LOGIN_URL = "https://itviec.com/customer/login"
APPS_URL = "https://itviec.com/customer/job-applications"
PAGE_SIZE = 100
APPLICATION_RE = re.compile(r"/customer/job-applications/([0-9a-f-]{16,})(?:/)?$", re.I)


class ITViecProvider(Provider):
    key = "itviec"
    display_name = "ITViec"
    website = "https://itviec.com"
    available = True
    request_jitter_ratio = 0.30
    page_jitter_ratio = 0.30

    def __init__(self, cfg, log=print):
        super().__init__(cfg, log)
        self.driver = None
        self.session = None  # giữ tương thích với mã/test cũ; request thật dùng thread-local
        self._local = threading.local()
        self._cookies = []
        self._ua = "Mozilla/5.0"
        self._total_count = 0
        self._last_page = 1
        self._first_page_items = []
        self._driver_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._throttle_lock = threading.Lock()
        self._next_request_at = 0.0
        self.email = account_for_source(cfg, self.key)
        self.password = (getattr(cfg, "itviec_password", "") or "").strip()

    @property
    def last_page(self):
        return self._last_page

    def concurrency_limit(self):
        return 3

    def minimum_item_delay_ms(self):
        return 300

    def minimum_page_delay_ms(self):
        return 500

    def _browser_cfg(self):
        return SimpleNamespace(
            headless=getattr(self.cfg, "headless", False),
            chrome_version=getattr(self.cfg, "chrome_version", 0),
            chromedriver_path=getattr(self.cfg, "chromedriver_path", ""),
            proxy_url=getattr(self.cfg, "proxy_url", ""),
            profile_dir=self.cfg.itviec_profile_dir,
        )

    @staticmethod
    def _is_login_page(response):
        url = (getattr(response, "url", "") or "").lower()
        if "/customer/login" in url:
            return True
        content_type = (getattr(response, "headers", {}).get("Content-Type", "") or "").lower()
        if "html" not in content_type:
            return False
        text = (getattr(response, "text", "") or "")[:120000].lower()
        return "customer_email" in text and "customer_password" in text

    @staticmethod
    def _is_applications_html(html):
        if not html:
            return False
        soup = BeautifulSoup(html, "html.parser")
        if soup.select_one("#customer_email, #customer_password"):
            return False
        return bool(soup.select_one('a[href*="/customer/job-applications/"]')
                    or soup.select_one('a[href*="page="]')
                    or "job applications" in soup.get_text(" ", strip=True).lower())

    def _read_browser_session(self):
        with self._driver_lock:
            self._cookies = self.driver.get_cookies()
            self._ua = self.driver.execute_script("return navigator.userAgent") or self._ua
        self._local = threading.local()

    def _new_session(self):
        session = requests.Session()
        net.apply(session, self.cfg)
        session.headers.update({
            "User-Agent": self._ua,
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": APPS_URL,
        })
        for cookie in self._cookies:
            name, value = cookie.get("name"), cookie.get("value")
            if not name:
                continue
            kwargs = {"path": cookie.get("path") or "/"}
            if cookie.get("domain"):
                kwargs["domain"] = cookie["domain"]
            session.cookies.set(name, value or "", **kwargs)
        return session

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._new_session()
            self._local.session = session
        return session

    def _wait_throttle(self):
        with self._throttle_lock:
            now = time.monotonic()
            ready = self._next_request_at
            delay = self.jitter_delay(0.10, self.request_jitter_ratio)
            self._next_request_at = max(now, ready) + delay
        if ready > now:
            time.sleep(min(ready - now, 60))

    @staticmethod
    def _retry_delay(response, attempt):
        try:
            retry_after = float(response.headers.get("Retry-After") or 0)
        except (TypeError, ValueError):
            retry_after = 0
        return min(60, retry_after or (2 ** (attempt + 1) + random.uniform(0.2, 0.8)))

    def _request(self, method, url, **kwargs):
        timeout = kwargs.pop("timeout", 40)
        last = None
        for attempt in range(4):
            self._wait_throttle()
            try:
                response = self._session().request(method, url, timeout=timeout, **kwargs)
                last = response
            except requests.RequestException as exc:
                if attempt == 3:
                    raise RuntimeError(f"Lỗi kết nối ITViec: {str(exc)[:120]}")
                time.sleep(2 ** attempt)
                continue
            if self._is_login_page(response) or response.status_code == 401:
                if attempt == 0 and self._refresh_session():
                    continue
                raise LoginError("Phiên ITViec đã hết hạn. Hãy đăng nhập/xác minh lại trên Chrome.")
            if response.status_code in (408, 429, 502, 503, 504) and attempt < 3:
                delay = self._retry_delay(response, attempt)
                self.log(f"ITViec tạm bận (HTTP {response.status_code}), thử lại sau {delay:.0f} giây...")
                time.sleep(delay)
                continue
            return response
        return last

    def _do_login(self):
        if not self.email or not self.password:
            raise LoginError("Chưa cấu hình Email/Mật khẩu ITViec trong mục Cấu hình.")
        safe_get(self.driver, LOGIN_URL, 1.0)
        selectors = {
            "email": [("id", "customer_email"), ("css selector", "input[type='email']"),
                      ("css selector", "input[placeholder*='email' i]")],
            "password": [("id", "customer_password"), ("css selector", "input[type='password']")],
        }

        email_el = self._visible_element(selectors["email"])
        password_el = self._visible_element(selectors["password"])
        if email_el is None or password_el is None:
            raise LoginError("Không tìm thấy form đăng nhập ITViec. Trang có thể vừa thay đổi giao diện.")
        email_el.clear()
        email_el.send_keys(self.email)
        password_el.clear()
        password_el.send_keys(self.password)
        # ITViec đặt các nút đổi ngôn ngữ EN/VI là type="submit" trước nút
        # đăng nhập. Không được chọn button[type=submit] chung chung vì nút EN
        # đang disabled còn nút VI sẽ chỉ đổi ngôn ngữ thay vì gửi form login.
        submit = self._visible_element([
            ("css selector", "button.ibtn-primary[type='submit']"),
            ("xpath", "//button[@type='submit' and normalize-space(.)='Sign in']"),
            ("xpath", "//button[@type='submit' and normalize-space(.)='Đăng nhập']"),
            ("css selector", "form:has(#customer_email) button[type='submit']:not([disabled])"),
        ])
        if submit is not None:
            submit.click()
        else:
            from selenium.webdriver.common.keys import Keys
            password_el.send_keys(Keys.RETURN)
        time.sleep(3)
        try:
            with self._driver_lock:
                still_login = "/customer/login" in (self.driver.current_url or "").lower()
                email_after = self.driver.find_element("id", "customer_email")
                form_was_cleared = not (email_after.get_attribute("value") or "")
            if still_login and form_was_cleared:
                self.log(
                    "ITViec đã nhận lần đăng nhập tự động nhưng trả lại trang đăng nhập. "
                    "Hãy kiểm tra tài khoản đã lưu và đăng nhập thủ công trên cửa sổ Chrome này một lần.")
        except Exception:
            pass

    def _visible_element(self, options):
        """Trả phần tử hiển thị và khả dụng đầu tiên trong danh sách selector."""
        for by, selector in options:
            try:
                element = self.driver.find_element(by, selector)
                if element.is_displayed() and element.is_enabled():
                    return element
            except Exception:
                pass
        return None

    def _browser_has_session(self):
        with self._driver_lock:
            url = (self.driver.current_url or "").lower()
            html = self.driver.page_source or ""
        return "/customer/login" not in url and self._is_applications_html(html)

    def _wait_login(self, minutes=5):
        bring_to_front(self.driver)
        self.log("ITViec cần đăng nhập/xác minh trên Chrome; phần mềm sẽ tự chạy tiếp khi thành công.")
        deadline = time.time() + minutes * 60
        while time.time() < deadline:
            try:
                if self._browser_has_session():
                    self._read_browser_session()
                    return
                with self._driver_lock:
                    current = (self.driver.current_url or "").lower()
                if "/customer/login" not in current:
                    safe_get(self.driver, APPS_URL, 0.5)
            except Exception:
                pass
            time.sleep(2)
        raise LoginError("Hết thời gian chờ đăng nhập ITViec. Hãy hoàn tất đăng nhập trên Chrome rồi thử lại.")

    def _refresh_session(self):
        if self.driver is None:
            return False
        with self._refresh_lock:
            safe_get(self.driver, APPS_URL, 0.5)
            if not self._browser_has_session():
                return False
            self._read_browser_session()
            return True

    def connect(self):
        try:
            self.log("Đang khởi động Chrome cho ITViec...")
            self.driver = start_driver(self._browser_cfg())
            safe_get(self.driver, APPS_URL, 0.8)
            if not self._browser_has_session():
                self.log("Chưa có phiên ITViec hợp lệ, đang thử đăng nhập tự động...")
                try:
                    self._do_login()
                except LoginError as exc:
                    self.log(str(exc))
                self._wait_login()
            else:
                self._read_browser_session()

            response = self._request("GET", APPS_URL, params={"page": 1, "per": PAGE_SIZE})
            if response.status_code != 200 or not self._is_applications_html(response.text):
                raise LoginError(f"Không đọc được danh sách ITViec (HTTP {response.status_code}).")
            self.session = self._session()
            self._parse_first_page(response.text)
            self.log(f"ITViec: tìm thấy {self._total_count:,} lượt ứng tuyển trên {self._last_page:,} trang.")
        except (LoginError, ChromeStartError):
            raise
        except Exception as exc:
            raise LoginError(f"Lỗi kết nối ITViec: {str(exc)[:160]}")

    @staticmethod
    def _parse_total(soup, item_count, last_page):
        text = soup.get_text(" ", strip=True)
        patterns = [
            r"(?:total|all)\s*(?:applications?)?\s*[:()]?\s*([\d.,]+)",
            r"([\d.,]+)\s*(?:applications?|candidates?)",
            r"(?:of|trên|tổng)\s+([\d.,]+)(?:\s|$)",
        ]
        candidates = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.I):
                try:
                    candidates.append(int(match.group(1).replace(",", "").replace(".", "")))
                except ValueError:
                    pass
        plausible = [n for n in candidates if n >= item_count and n >= (last_page - 1) * PAGE_SIZE]
        if plausible:
            return min(plausible)
        if last_page > 1:
            return (last_page - 1) * PAGE_SIZE + item_count
        return item_count

    def _parse_first_page(self, html):
        soup = BeautifulSoup(html, "html.parser")
        items = self._parse_items(html)
        pages = [1]
        for link in soup.select('a[href*="page="]'):
            match = re.search(r"[?&]page=(\d+)", link.get("href", ""))
            if match:
                pages.append(int(match.group(1)))
        self._last_page = max(pages)
        self._total_count = self._parse_total(soup, len(items), self._last_page)
        if self._total_count:
            self._last_page = max(self._last_page, math.ceil(self._total_count / PAGE_SIZE))
        self._first_page_items = items

    def total_count(self):
        return self._total_count

    def peek_first_page(self):
        return list(self._first_page_items)

    def iter_pages(self, start_page=1, end_page=None, reverse=False):
        end_page = min(int(end_page or self._last_page), self._last_page)
        pages = list(range(max(1, int(start_page or 1)), end_page + 1))
        if reverse:
            pages.reverse()
        for page in pages:
            if page == 1 and self._first_page_items:
                yield page, list(self._first_page_items)
                continue
            response = self._request("GET", APPS_URL, params={"page": page, "per": PAGE_SIZE})
            if response.status_code != 200:
                raise RuntimeError(f"Không tải được trang ITViec {page} (HTTP {response.status_code}).")
            items = self._parse_items(response.text)
            if not items:
                raise RuntimeError(f"Trang ITViec {page} không có dữ liệu; đã dừng để tránh checkpoint sai.")
            yield page, items

    @staticmethod
    def _parse_applied(value):
        value = (value or "").strip()
        for fmt in ("%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(value, fmt)
                return dt.strftime("%d/%m/%Y %H:%M"), dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        return value, ""

    #: Khớp HOẶC một dãy số liền nhau (8-10 số, phổ biến nhất) HOẶC số được
    #: chia nhóm bằng ĐÚNG một dấu cách/chấm/gạch giữa các nhóm ≥2 chữ số (kiểu
    #: hiển thị "090 123 4567"). KHÔNG dùng một lớp ký tự gộp chung số và dấu
    #: cách: đó là cách cũ từng nuốt nhầm chữ số của từ liền sau số điện thoại
    #: (vd nhãn "N years experience" ngay sau, chỉ cách một dấu cách) vào cuối
    #: số điện thoại — sai mà không có gì báo lỗi. Xem memory
    #: `edge-dom-text-regex-swallow-bug`. Nhánh `\d{8,10}` không thể bắc cầu
    #: qua dấu cách (không nằm trong lớp `\d`) nên tự dừng đúng chỗ; nhánh
    #: nhóm-có-dấu-cách đòi mỗi nhóm sau dấu cách phải ≥2 chữ số nên không
    #: khớp một chữ số lẻ loi đứng sau dấu cách.
    _PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:\d{8,10}|\d{2,4}(?:[ .\-]\d{2,4}){1,3})(?!\d)")

    @classmethod
    def _extract_phone(cls, text):
        match = cls._PHONE_RE.search(text)
        if not match:
            return ""
        normalized = re.sub(r"[^\d+]", "", match.group(0))
        if normalized.startswith("+84"):
            normalized = "0" + normalized[3:]
        elif normalized.startswith("84") and len(normalized) == 11:
            normalized = "0" + normalized[2:]
        # Kiểm độ dài làm lưới an toàn thứ hai (không phải cơ chế chặn chính).
        return normalized if normalized.startswith("0") and 9 <= len(normalized) <= 11 else ""

    def _parse_items(self, html):
        soup = BeautifulSoup(html, "html.parser")
        seen, items = set(), []
        for link in soup.select('a[href*="/customer/job-applications/"]:not([href*="/downloads"])'):
            href = urlparse(link.get("href", "")).path.rstrip("/")
            match = APPLICATION_RE.search(href)
            if not match or match.group(1) in seen:
                continue
            cv_id = match.group(1)
            seen.add(cv_id)
            row, job_link = link, None
            for _ in range(8):
                row = row.parent
                if row is None or row.name in ("body", "html"):
                    break
                job_link = row.select_one('a[href*="/customer/jobs/"]')
                if job_link:
                    break
            text = row.get_text(" ", strip=True) if row else link.get_text(" ", strip=True)
            email = re.search(r"[\w.%+\-]+@[\w.\-]+\.[A-Za-z]{2,}", text)
            date = re.search(r"\d{2}[-/]\d{2}[-/]\d{4}(?:\s+\d{2}:\d{2})?", text)
            applied_at, applied_ts = self._parse_applied(date.group(0) if date else "")
            job_href = job_link.get("href", "") if job_link else ""
            campaign = re.search(r"/customer/jobs/([^/?#]+)", job_href)
            items.append({
                "source": self.key, "account": self.email, "cv_id": cv_id,
                "fullname": link.get_text(" ", strip=True),
                "email": email.group(0) if email else "",
                "phone": self._extract_phone(text),
                "position": job_link.get_text(" ", strip=True) if job_link else "",
                "campaign_id": campaign.group(1) if campaign else "",
                "applied_at": applied_at, "applied_ts": applied_ts,
                "apply_source": "ITViec", "status": "Applied",
                "cv_url": urljoin(self.website, href),
            })
        return items

    @staticmethod
    def _filename_from_disposition(value):
        if not value:
            return ""
        message = Message()
        message["content-disposition"] = value
        filename = message.get_filename() or ""
        return unquote(filename)

    @staticmethod
    def _detect_file(data, content_type="", filename=""):
        head = data[:1024]
        lower_type = (content_type or "").lower()
        suffix = (filename.rsplit(".", 1)[-1].lower() if "." in filename else "")
        pdf_at = head.find(b"%PDF")
        if 0 <= pdf_at < 1024:
            return ".pdf"
        if data.startswith(b"\xd0\xcf\x11\xe0"):
            return ".doc"
        if data.startswith(b"PK\x03\x04"):
            return ".docx" if suffix in ("docx", "") or "wordprocessingml" in lower_type else ".zip"
        if data.startswith(b"{\\rtf"):
            return ".rtf"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if data.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        return None

    def download(self, item_or_id):
        cv_id = str(item_or_id.get("cv_id", "") if isinstance(item_or_id, dict) else item_or_id)
        if not APPLICATION_RE.fullmatch(f"/customer/job-applications/{cv_id}"):
            return None, "Mã hồ sơ ITViec không hợp lệ."
        url = f"{APPS_URL}/{cv_id}/downloads"
        response = self._request("GET", url, allow_redirects=True, timeout=60)
        http_status = response.status_code
        if http_status == 200 and response.content:
            data = response.content
            filename = self._filename_from_disposition(response.headers.get("Content-Disposition", ""))
            extension = self._detect_file(data, response.headers.get("Content-Type", ""), filename)
            if extension:
                return data, extension

        # Dự phòng: gọi lại đúng địa chỉ đó trong Chrome đã đăng nhập. Bắt được
        # trường hợp tường lửa công ty chặn riêng đường tải của thư viện HTTP,
        # hoặc ITViec trả lỗi giả cho client không phải trình duyệt.
        status, data = browser_fetch_bytes(
            self.driver, self._driver_lock, "GET", url, credentials="include")
        if data:
            extension = self._detect_file(data, "", "")
            if extension:
                return data, extension

        if http_status in (403, 404, 410, 422):
            return None, f"CV không còn hoặc tài khoản không có quyền tải (HTTP {http_status})."
        if http_status != 200:
            return None, f"Lỗi HTTP {http_status}."
        return None, "ITViec trả về nội dung không phải file CV (có thể phiên đã hết hạn)."

    def close(self):
        session = getattr(self._local, "session", None)
        if session:
            try:
                session.close()
            except Exception:
                pass
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
