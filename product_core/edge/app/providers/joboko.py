# -*- coding: utf-8 -*-
"""Provider Joboko (cổng nhà tuyển dụng em-vn.joboko.com).

Danh sách `/cv` = ứng viên đã ứng tuyển vào các tin của nhà tuyển dụng. Khác các
kênh kia, Joboko chạy HOÀN TOÀN trong trình duyệt:

* Phân trang là JavaScript (`?page=N` không có tác dụng) → phải BẤM nút số trang.
* Nút "Tải CV" trên trang chi tiết là JavaScript (href = "#…") → phải BẤM và bắt
  file trình duyệt tự tải xuống (CDP `Page.setDownloadBehavior`).

Vì chỉ có một cửa sổ Chrome nên provider chạy TUẦN TỰ (`concurrency_limit() == 1`).

Cấu trúc DOM đã đối chiếu site thật (2026-09):
  - dòng ứng viên:   ``a.text-view-cv[href="…/xem-ho-so-<hex>-<id>?…"]`` , text = tên
  - tổng số hồ sơ:   ``span.data-row``  (vd "89")  → 10 hồ sơ / trang
  - phân trang:      ``ul.pagination li.page-item``  (text = số trang) + ``.next`` / ``.prev`` / ``.last``
  - nút tải:         ``a.btn-download-file``  (text "Tải CV")
"""
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import Provider, LoginError
from ..browser import ChromeStartError, bring_to_front, safe_get, start_driver
from ..config import account_for_source
from ..state_paths import local_state_dir

WEB = "https://em-vn.joboko.com"
LOGIN_URL = f"{WEB}/dang-nhap"
LIST_URL = f"{WEB}/cv"
PAGE_SIZE = 10
DETAIL_ID_RE = re.compile(r"/xem-ho-so-[0-9a-fA-F]+-(\d+)")

LOGIN_EMAIL_SELECTORS = (
    ("css selector", "input[type='email']"),
    ("css selector", "input[name*='email' i]"),
    ("css selector", "input[name*='account' i]"),
    ("css selector", "input[name='username']"),
    ("css selector", "form input[type='text']:not([type='hidden'])"),
)
LOGIN_PASSWORD_SELECTORS = (
    ("css selector", "input[type='password']"),
    ("css selector", "input[name*='pass' i]"),
)
LOGIN_SUBMIT_SELECTORS = (
    ("xpath", "//button[contains(normalize-space(.), 'Đăng nhập')]"),
    ("xpath", "//input[@type='submit']"),
    ("css selector", "form button[type='submit']:not([disabled])"),
    ("css selector", "button[type='submit']"),
)


class JobokoProvider(Provider):
    key = "joboko"
    display_name = "Joboko"
    website = WEB
    available = True
    request_jitter_ratio = 0.30
    page_jitter_ratio = 0.30
    #: Joboko không có API tải nhanh; danh sách + tải đều qua chính cửa sổ Chrome.
    max_concurrency = 1
    #: Cho engine mở lại trang chi tiết cho hồ sơ cũ (chưa detail_loaded) để
    #: bóc vị trí ứng tuyển + mã tin từ biến JS `jbkCVInfo`.
    supports_detail_enrichment = True

    def __init__(self, cfg, log=print):
        super().__init__(cfg, log)
        self.driver = None
        self._driver_lock = threading.RLock()
        self._total_count = 0
        self._last_page = 1
        self._first_page_items = []
        self._dumped = False
        self.email = account_for_source(cfg, self.key)
        self.password = (getattr(cfg, "joboko_password", "") or "").strip()

    # ---------------------------------------------------------------- contract
    @property
    def last_page(self):
        return self._last_page

    def concurrency_limit(self):
        return 1

    def minimum_item_delay_ms(self):
        return 800

    def minimum_page_delay_ms(self):
        return 1200

    def total_count(self):
        return self._total_count

    def peek_first_page(self):
        return list(self._first_page_items)

    # ---------------------------------------------------------------- browser
    def _force_headless(self):
        """Người dùng đã ép ẩn toàn cục ('Ẩn cửa sổ Chrome') -> luôn ẩn, kể cả khi đăng nhập."""
        return bool(getattr(self.cfg, "headless", False))

    def _prefer_headless(self):
        """Joboko điều khiển cả cửa sổ suốt lượt nên mặc định chạy ẩn cho nhẹ máy;
        chỉ tự hiện lên khi cần đăng nhập (trừ khi bị ép ẩn toàn cục)."""
        return self._force_headless() or bool(getattr(self.cfg, "joboko_headless", True))

    def _browser_cfg(self, headless):
        return SimpleNamespace(
            headless=bool(headless),
            chrome_version=getattr(self.cfg, "chrome_version", 0),
            chromedriver_path=getattr(self.cfg, "chromedriver_path", ""),
            proxy_url=getattr(self.cfg, "proxy_url", ""),
            profile_dir=self.cfg.joboko_profile_dir,
        )

    def _restart_driver(self, headless):
        with self._driver_lock:
            if self.driver is not None:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
            time.sleep(1.0)
            self.driver = start_driver(self._browser_cfg(headless))

    def _html(self):
        with self._driver_lock:
            return self.driver.page_source or ""

    def _url(self):
        with self._driver_lock:
            try:
                return (self.driver.current_url or "").lower()
            except Exception:
                return ""

    def _visible_element(self, options):
        for by, selector in options:
            try:
                element = self.driver.find_element(by, selector)
                if element.is_displayed() and element.is_enabled():
                    return element
            except Exception:
                pass
        return None

    def _on_login_page(self):
        if "/dang-nhap" in self._url() or "/login" in self._url():
            return True
        with self._driver_lock:
            try:
                return any(e.is_displayed() for e in
                           self.driver.find_elements("css selector", "input[type='password']"))
            except Exception:
                return False

    def _wait_list(self, seconds=20):
        """Chờ DOM có dòng ứng viên (site dựng danh sách bằng JavaScript)."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._on_login_page():
                return
            with self._driver_lock:
                try:
                    if self.driver.find_elements("css selector", "a.text-view-cv[href]"):
                        return
                    # trang có thể trống thật (0 hồ sơ) nhưng vẫn có khung
                    if self.driver.find_elements("css selector", "span.data-row, .pagination"):
                        return
                except Exception:
                    pass
            time.sleep(0.8)

    def _has_session(self):
        if self._on_login_page():
            return False
        self._wait_list(seconds=8)
        soup = BeautifulSoup(self._html(), "html.parser")
        return bool(soup.select_one("a.text-view-cv, span.data-row")
                    or "quản lý cv" in soup.get_text(" ", strip=True).lower())

    def _do_login(self):
        if not self.email or not self.password:
            raise LoginError("Chưa cấu hình Email/Mật khẩu Joboko trong mục Cấu hình.")
        safe_get(self.driver, LOGIN_URL, 1.4)
        email_el = self._visible_element(LOGIN_EMAIL_SELECTORS)
        password_el = self._visible_element(LOGIN_PASSWORD_SELECTORS)
        if email_el is None or password_el is None:
            raise LoginError("Không tìm thấy form đăng nhập Joboko. Trang có thể vừa đổi giao diện.")
        email_el.clear()
        email_el.send_keys(self.email)
        password_el.clear()
        password_el.send_keys(self.password)
        time.sleep(0.6)
        submit = self._visible_element(LOGIN_SUBMIT_SELECTORS)
        if submit is not None:
            submit.click()
        else:
            from selenium.webdriver.common.keys import Keys
            password_el.send_keys(Keys.RETURN)
        time.sleep(4)

    def _wait_login(self, minutes=5):
        bring_to_front(self.driver)
        self.log("Joboko cần đăng nhập/xác minh trên Chrome; phần mềm sẽ tự chạy tiếp khi xong.")
        deadline = time.time() + minutes * 60
        while time.time() < deadline:
            try:
                safe_get(self.driver, LIST_URL, 0.6)
                if self._has_session():
                    return
            except Exception:
                pass
            time.sleep(2)
        raise LoginError("Hết thời gian chờ đăng nhập Joboko. Hãy đăng nhập trên Chrome rồi thử lại.")

    def refresh_failed_item(self, item):
        return False

    # ---------------------------------------------------------------- connect
    def connect(self):
        try:
            headless = self._prefer_headless()
            self.log("Đang khởi động Chrome cho Joboko"
                     + (" (chạy ẩn)..." if headless else "..."))
            self.driver = start_driver(self._browser_cfg(headless))
            safe_get(self.driver, LIST_URL, 1.0)
            self._wait_list()
            if not self._has_session():
                # Cần đăng nhập: nếu đang ẩn thì bật cửa sổ lên để còn giải
                # captcha/OTP (trừ khi người dùng ép ẩn toàn cục).
                if headless and not self._force_headless():
                    self.log("Cần đăng nhập Joboko — mở cửa sổ Chrome để bạn xác minh.")
                    self._restart_driver(headless=False)
                    safe_get(self.driver, LIST_URL, 1.0)
                    self._wait_list()
                if not self._has_session():
                    self.log("Chưa có phiên Joboko hợp lệ, đang thử đăng nhập tự động...")
                    try:
                        self._do_login()
                    except LoginError as exc:
                        self.log(str(exc))
                    if not self._has_session():
                        self._wait_login()

            safe_get(self.driver, LIST_URL, 1.0)
            self._wait_list()
            html = self._html()
            items = self._parse_items(html)
            self._total_count = self._parse_total(html, len(items))
            self._last_page = max(1, math.ceil(self._total_count / PAGE_SIZE)) if self._total_count else 1
            self._first_page_items = items
            if not items and self._total_count:
                self._dump_debug(html)
                raise LoginError(
                    "Joboko báo có hồ sơ nhưng không đọc được dòng nào (giao diện có thể vừa đổi). "
                    "Đã lưu HTML trang /cv để kiểm tra — xem dòng ⓘ ở trên.")
            self.log(f"Joboko: tìm thấy {self._total_count:,} lượt ứng tuyển "
                     f"trên {self._last_page:,} trang.")
        except (LoginError, ChromeStartError):
            raise
        except Exception as exc:
            raise LoginError(f"Lỗi kết nối Joboko: {str(exc)[:160]}")

    # ---------------------------------------------------------------- parse
    @staticmethod
    def _parse_total(html, item_count):
        soup = BeautifulSoup(html or "", "html.parser")
        node = soup.select_one("span.data-row")
        if node and node.get_text(strip=True).replace(".", "").replace(",", "").isdigit():
            return int(node.get_text(strip=True).replace(".", "").replace(",", ""))
        match = re.search(r"Tìm thấy\s*([\d.,]+)\s*hồ sơ", soup.get_text(" ", strip=True), re.I)
        if match:
            return int(match.group(1).replace(".", "").replace(",", ""))
        return item_count

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

    def _parse_items(self, html):
        soup = BeautifulSoup(html or "", "html.parser")
        if soup.select_one("input[type='password']") and not soup.select_one("a.text-view-cv"):
            return []
        seen, items = set(), []
        for link in soup.select("a.text-view-cv[href]"):
            match = DETAIL_ID_RE.search(link.get("href", ""))
            if not match:
                continue
            cv_id = match.group(1)
            if cv_id in seen:
                continue
            seen.add(cv_id)

            row = link
            for _ in range(6):
                row = row.parent
                if row is None or row.name in ("body", "html"):
                    row = link
                    break
                classes = row.get("class") or []
                if "item" in classes or len(row.get_text(" ", strip=True)) > 80:
                    break
            text = row.get_text(" ", strip=True) if row else link.get_text(" ", strip=True)

            href = link.get("href", "")
            # `jid` (mã tin đã ứng tuyển) luôn có trong href danh sách; nhóm
            # ứng viên theo tin ngay cả khi chưa mở trang chi tiết. Tên tin lấy
            # sau ở enrich()/download() qua `jbkCVInfo.TxtNote`.
            jid = parse_qs(urlparse(href).query).get("jid", [""])[0]

            name = link.get_text(" ", strip=True).strip() or f"Ứng viên {cv_id}"
            email = re.search(r"[\w.%+\-]+@[\w.\-]+\.[A-Za-z]{2,}", text)
            # HOẶC dãy số liền nhau, HOẶC số chia nhóm bằng đúng 1 dấu cách/gạch
            # giữa các nhóm ≥2 chữ số ("090 123 4567") — không dùng lớp ký tự
            # gộp chung số+dấu cách: kiểu đó từng nuốt nhầm chữ số của từ liền
            # sau (đã gặp thật ở JobsGO, nhãn "N file" ngay sau số điện thoại)
            # vào cuối số điện thoại. Xem memory edge-dom-text-regex-swallow-bug.
            phone = re.search(
                r"(?<!\d)(?:\+?84|0)(?:\d{8,10}|\d{2,4}(?:[ .\-]\d{2,4}){1,3})(?!\d)", text)
            date = re.search(r"\d{2}[-/]\d{2}[-/]\d{4}(?:\s+\d{2}:\d{2})?", text)
            applied_at, applied_ts = self._parse_applied(date.group(0) if date else "")

            items.append({
                "source": self.key, "account": self.email, "cv_id": cv_id,
                "fullname": name,
                "email": email.group(0).lower() if email else "",
                "phone": re.sub(r"[^\d+]", "", phone.group(0)) if phone else "",
                "position": "", "campaign_id": jid,
                "applied_at": applied_at, "applied_ts": applied_ts,
                "apply_source": "Joboko", "status": "Applied",
                "cv_url": urljoin(WEB, href),
            })
        return items

    # ---------------------------------------------------------------- phân trang
    def _active_page(self):
        with self._driver_lock:
            try:
                node = self.driver.find_element("css selector", "li.page-item.active")
                text = (node.text or "").strip()
                return int(text) if text.isdigit() else 1
            except Exception:
                return 1

    def _click_pager(self, css):
        with self._driver_lock:
            try:
                elements = self.driver.find_elements("css selector", css)
            except Exception:
                return False
            for el in elements:
                try:
                    if el.is_displayed():
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});arguments[0].click();", el)
                        return True
                except Exception:
                    continue
        return False

    def _click_page_number(self, page):
        with self._driver_lock:
            try:
                items = self.driver.find_elements("css selector", "ul.pagination li.page-item")
            except Exception:
                return False
        for el in items:
            try:
                if (el.text or "").strip() == str(page) and "active" not in (el.get_attribute("class") or ""):
                    with self._driver_lock:
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});"
                            "arguments[0].querySelector('a,button,span')?.click()||arguments[0].click();", el)
                    return True
            except Exception:
                continue
        return False

    def _goto_page(self, page):
        """Bấm phân trang cho tới khi trang đang active đúng bằng `page`."""
        for _ in range(page + 40):
            current = self._active_page()
            if current == page:
                return True
            first_before = self._first_id()
            moved = (self._click_page_number(page)
                     or self._click_pager("li.page-item.next:not(.disabled) a, li.page-item.next:not(.disabled)")
                     if current < page else
                     self._click_pager("li.page-item.prev:not(.disabled) a, li.page-item.prev:not(.disabled)"))
            if not moved:
                return False
            # chờ DOM đổi
            for _ in range(30):
                time.sleep(0.3)
                if self._active_page() == page or self._first_id() != first_before:
                    break
            time.sleep(self.jitter_delay(0.6, self.page_jitter_ratio))
        return self._active_page() == page

    def _first_id(self):
        match = DETAIL_ID_RE.search(self._html())
        return match.group(1) if match else ""

    def iter_pages(self, start_page=1, end_page=None, reverse=False):
        end_page = min(int(end_page or self._last_page), self._last_page)
        start_page = max(1, int(start_page or 1))
        pages = list(range(start_page, end_page + 1))
        if reverse:
            pages.reverse()
        for page in pages:
            if page == 1 and self._first_page_items and not reverse:
                yield 1, list(self._first_page_items)
                continue
            with self._driver_lock:
                on_list = "/cv" in self._url() and not self._on_login_page()
            if not on_list:
                safe_get(self.driver, LIST_URL, 1.0)
                self._wait_list()
            if not self._goto_page(page):
                raise RuntimeError(f"Không chuyển được sang trang Joboko {page}.")
            self._wait_list(seconds=12)
            items = self._parse_items(self._html())
            if not items:
                raise RuntimeError(
                    f"Trang Joboko {page} không có dữ liệu; đã dừng để tránh checkpoint sai.")
            yield page, items

    # ------------------------------------------------- trường trên trang chi tiết
    #: Joboko nhét dữ liệu ứng tuyển vào biến JS `var jbkCVInfo = '{...}'`
    #: (JSON) trong một <script> ở trang chi tiết. Phần còn lại của trang là
    #: PDF CV trong iframe — KHÔNG có block thông tin cấu trúc nào khác, nên
    #: đây là nguồn DUY NHẤT cho vị trí ứng tuyển + mã tin (ngoài `jid` ở href).
    _CV_INFO_RE = re.compile(r"jbkCVInfo\s*=\s*'(\{.*?\})'", re.S)
    _EMPTY_VALUES = ("", "-", "n/a", "chưa cập nhật", "không có", "đang cập nhật")

    @classmethod
    def _parse_detail_fields(cls, html):
        match = cls._CV_INFO_RE.search(html or "")
        if not match:
            return {}
        try:
            info = json.loads(match.group(1))
        except (ValueError, TypeError):
            return {}
        out = {}
        job_id = str(info.get("IdJob") or info.get("IdCamp") or "").strip()
        if job_id and job_id.lower() not in cls._EMPTY_VALUES:
            out["campaign_id"] = job_id[:60]
        # TxtNote: "Ứng viên <tên> ứng tuyển việc làm <VỊ TRÍ>"
        note = str(info.get("TxtNote") or "").strip()
        found = re.search(r"ứng tuyển(?:\s+việc\s+làm)?\s+(.+?)\s*$", note, re.I)
        if found:
            position = found.group(1).strip(" .:-—|·")
            if position and position.lower() not in cls._EMPTY_VALUES:
                out["position"] = position[:150]
        return out

    def _apply_detail_fields(self, item, html):
        for key, value in self._parse_detail_fields(html).items():
            if value and not str(item.get(key) or "").strip():
                item[key] = value
        item["detail_loaded"] = 1

    def enrich(self, item):
        """Engine gọi cho hồ sơ cũ (đã tải CV, chưa detail_loaded) khi chạy
        'Tải tất cả' — chỉ mở trang chi tiết đọc `jbkCVInfo`, không tải lại
        file. Lỗi phải ném ra để engine ghi nhận, KHÔNG nuốt."""
        detail_url = item.get("cv_url")
        if not detail_url:
            return
        with self._driver_lock:
            safe_get(self.driver, detail_url, 1.2)
            if self._on_login_page():
                raise LoginError("Phiên Joboko đã hết hạn. Hãy đăng nhập lại trên Chrome.")
            html = self.driver.page_source or ""
        self._apply_detail_fields(item, html)

    # ---------------------------------------------------------------- tải CV
    @staticmethod
    def _detect_file(data):
        if not data:
            return None
        if 0 <= data[:1024].find(b"%PDF") < 1024:
            return ".pdf"
        if data.startswith(b"\xd0\xcf\x11\xe0"):
            return ".doc"
        if data.startswith(b"PK\x03\x04"):
            return ".docx"
        if data.startswith(b"{\\rtf"):
            return ".rtf"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if data.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        return None

    def download(self, item_or_id):
        item = item_or_id if isinstance(item_or_id, dict) else {"cv_id": str(item_or_id)}
        # Không có link thật (dữ liệu cũ/hỏng) thì báo lỗi rõ ràng thay vì đoán ra
        # một URL sai khuôn (thiếu mã hex) chắc chắn 404.
        detail_url = item.get("cv_url")
        if not detail_url:
            return None, "Thiếu đường dẫn hồ sơ Joboko (chưa từng quét lại danh sách?)."
        if "joboko.com" not in urlparse(detail_url).netloc:
            return None, "Đường dẫn hồ sơ Joboko không hợp lệ."

        folder = tempfile.mkdtemp(prefix="msbradar-joboko-")
        try:
            with self._driver_lock:
                safe_get(self.driver, detail_url, 1.5)
                if self._on_login_page():
                    raise LoginError("Phiên Joboko đã hết hạn. Hãy đăng nhập lại trên Chrome.")
                # Trang chi tiết đã mở sẵn để tìm nút tải — tiện thể bóc luôn vị
                # trí ứng tuyển + mã tin từ `jbkCVInfo`. Chỉ điền khi item trống.
                if isinstance(item_or_id, dict):
                    try:
                        self._apply_detail_fields(item, self.driver.page_source or "")
                    except Exception:
                        pass
                try:
                    self.driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                        "behavior": "allow", "downloadPath": folder})
                except Exception:
                    pass
                button = None
                for _ in range(20):
                    try:
                        found = self.driver.find_elements(
                            "css selector", "a.btn-download-file, .btn-download-file")
                        found = [b for b in found if b.is_displayed()]
                        if found:
                            button = found[0]
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)
                if button is None:
                    return None, "Không tìm thấy nút 'Tải CV' trên trang hồ sơ Joboko."
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});arguments[0].click();", button)

            deadline = time.time() + 60
            while time.time() < deadline:
                names = [n for n in os.listdir(folder) if not n.endswith((".crdownload", ".tmp"))]
                if names:
                    path = os.path.join(folder, names[0])
                    if os.path.getsize(path) > 0:
                        with open(path, "rb") as handle:
                            data = handle.read()
                        ext = self._detect_file(data)
                        if ext:
                            return data, ext
                        return None, "Nội dung tải về không phải file CV hợp lệ."
                time.sleep(0.5)
            return None, "Joboko không trả file sau khi bấm 'Tải CV' (có thể hết điểm hoặc phiên lỗi)."
        except LoginError:
            raise
        except Exception as exc:
            return None, f"Lỗi tải CV Joboko: {str(exc)[:150]}"
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    # ---------------------------------------------------------------- misc
    def _dump_debug(self, html):
        if self._dumped:
            return
        self._dumped = True
        try:
            path = os.path.join(local_state_dir(), "joboko_cv_dump.html")
            with open(path, "w", encoding="utf-8", errors="replace") as handle:
                handle.write(html or "")
            soup = BeautifulSoup(html or "", "html.parser")
            self.log(f"  ⓘ Đã lưu trang /cv để đối chiếu: {path} "
                     f"(URL {self._url()}, {len(soup.find_all('a'))} link).")
        except Exception as exc:
            self.log(f"  ! Không ghi được joboko_cv_dump.html: {str(exc)[:120]}")

    def close(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
