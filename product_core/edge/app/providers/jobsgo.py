# -*- coding: utf-8 -*-
"""Provider JobsGO (cổng nhà tuyển dụng employer.jobsgo.vn).

`employer.jobsgo.vn` đứng sau Cloudflare Bot Management: `requests` bị chặn
(HTTP 403 "Just a moment...") dù dùng đúng cookie phiên + User-Agent của trình
duyệt đã đăng nhập, và Chrome chạy **headless cũng bị chặn** — chỉ Chrome chạy
CÓ cửa sổ mới qua được. Vì vậy danh sách + trang chi tiết PHẢI đọc qua trình
duyệt thật (không headless).

Khác Joboko: phân trang ở đây là URL thật (`?page=N&per-page=100` điều hướng
được thẳng, không cần bấm), và file CV không nằm sau Cloudflare — nút "Tải
xuống" trỏ qua `/tool/download?...&l=<url-encoded>` với `l` là link CDN thô
(`media.jobsgo.vn`/`jobsgo.vn/uploads/...`) không có Cloudflare. Nên tải file
chỉ cần giải mã `l` rồi `requests.get()` thẳng — nhanh, không cần trình duyệt.

Vì liệt kê + trang chi tiết vẫn phải qua đúng một cửa sổ Chrome, provider vẫn
chạy tuần tự (`concurrency_limit() == 1`) như Joboko.
"""
import math
import os
import re
import shutil
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .base import Provider, LoginError
from .topcv import sniff_ext, response_ext
from ..browser import ChromeStartError, bring_to_front, safe_get, start_driver
from ..config import account_for_source
from ..state_paths import local_state_dir
from .. import net

WEB = "https://employer.jobsgo.vn"
LOGIN_URL = f"{WEB}/site/login"
LIST_URL = f"{WEB}/candidate/all"
PAGE_SIZE = 100

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


class JobsGoProvider(Provider):
    key = "jobsgo"
    display_name = "JobsGO"
    website = WEB
    available = True
    request_jitter_ratio = 0.30
    page_jitter_ratio = 0.20
    #: Danh sách/chi tiết phải qua đúng một cửa sổ Chrome (Cloudflare chặn requests).
    max_concurrency = 1
    #: Cho engine tự mở chi tiết bổ sung dữ liệu cho hồ sơ cũ (chưa detail_loaded)
    #: khi chạy "Tải tất cả" - lấy "Làm việc tại" (nơi làm việc mong muốn) v.v.
    supports_detail_enrichment = True

    def __init__(self, cfg, log=print):
        super().__init__(cfg, log)
        self.driver = None
        self._driver_lock = threading.RLock()
        self._local = threading.local()
        self._total_count = 0
        self._last_page = 1
        self._first_page_items = []
        self._dumped = False
        self.email = account_for_source(cfg, self.key)
        self.password = (getattr(cfg, "jobsgo_password", "") or "").strip()

    # ---------------------------------------------------------------- contract
    @property
    def last_page(self):
        return self._last_page

    def concurrency_limit(self):
        return 1

    def minimum_item_delay_ms(self):
        return 500

    def minimum_page_delay_ms(self):
        return 900

    def total_count(self):
        return self._total_count

    def peek_first_page(self):
        return list(self._first_page_items)

    def refresh_failed_item(self, item):
        return False

    # ---------------------------------------------------------------- browser
    def _browser_cfg(self):
        return SimpleNamespace(
            # Cloudflare Bot Management chặn Chrome headless trên site này (đã
            # kiểm chứng: cùng driver, chỉ khác cờ --headless=new là bị chặn) —
            # khác các kênh kia, KHÔNG cho tự ý ẩn cửa sổ ở đây.
            headless=False,
            chrome_version=getattr(self.cfg, "chrome_version", 0),
            chromedriver_path=getattr(self.cfg, "chromedriver_path", ""),
            proxy_url=getattr(self.cfg, "proxy_url", ""),
            profile_dir=self.cfg.jobsgo_profile_dir,
        )

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
        if "/login" in self._url():
            return True
        with self._driver_lock:
            try:
                return any(e.is_displayed() for e in
                           self.driver.find_elements("css selector", "input[type='password']"))
            except Exception:
                return False

    def _wait_list_dom(self, seconds=15):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._on_login_page():
                return
            with self._driver_lock:
                try:
                    if self.driver.find_elements("css selector", "a.candidate-name-link[href]"):
                        return
                except Exception:
                    pass
            time.sleep(0.6)

    def _has_session(self):
        if self._on_login_page():
            return False
        self._wait_list_dom(seconds=8)
        soup = BeautifulSoup(self._html(), "html.parser")
        return bool(soup.select_one("a.candidate-name-link")
                    or "ứng viên ứng tuyển" in soup.get_text(" ", strip=True).lower())

    def _do_login(self):
        if not self.email or not self.password:
            raise LoginError("Chưa cấu hình Email/Mật khẩu JobsGO trong mục Cấu hình.")
        safe_get(self.driver, LOGIN_URL, 1.4)
        # Cloudflare xử lý xong "thử thách" JS rồi mới chuyển hẳn sang trang đăng
        # nhập thật; trên một profile Chrome hoàn toàn mới việc đó có thể mất vài
        # giây, nên chỉ tìm MỘT lần ngay khi vừa mở trang dễ báo nhầm "không có
        # form" trong khi thực ra trang đang tự chuyển. Thử lại thêm vài lần.
        email_el = password_el = None
        for _ in range(6):
            email_el = self._visible_element(LOGIN_EMAIL_SELECTORS)
            password_el = self._visible_element(LOGIN_PASSWORD_SELECTORS)
            if email_el is not None and password_el is not None:
                break
            time.sleep(1.5)
        if email_el is None or password_el is None:
            raise LoginError("Không tìm thấy form đăng nhập JobsGO. Trang có thể vừa đổi giao diện.")
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
        self.log("JobsGO cần đăng nhập/xác minh trên Chrome; phần mềm sẽ tự chạy tiếp khi xong.")
        deadline = time.time() + minutes * 60
        while time.time() < deadline:
            try:
                safe_get(self.driver, LIST_URL, 0.6)
                if self._has_session():
                    return
            except Exception:
                pass
            time.sleep(2)
        raise LoginError("Hết thời gian chờ đăng nhập JobsGO. Hãy đăng nhập trên Chrome rồi thử lại.")

    # ---------------------------------------------------------------- connect
    def connect(self):
        try:
            self.log("Đang khởi động Chrome cho JobsGO...")
            self.driver = start_driver(self._browser_cfg())
            safe_get(self.driver, LIST_URL, 1.0)
            self._wait_list_dom()
            if not self._has_session():
                self.log("Chưa có phiên JobsGO hợp lệ, đang thử đăng nhập tự động...")
                try:
                    self._do_login()
                except LoginError as exc:
                    self.log(str(exc))
                if not self._has_session():
                    self._wait_login()

            html = self._goto_list_page(1)
            items = self._parse_items(html)
            self._total_count = self._parse_total(html, len(items))
            self._last_page = max(1, math.ceil(self._total_count / PAGE_SIZE)) if self._total_count else 1
            self._first_page_items = items
            if not items and self._total_count:
                self._dump_debug(html)
                raise LoginError(
                    "JobsGO báo có ứng viên nhưng không đọc được dòng nào (giao diện có thể vừa "
                    "đổi). Đã lưu HTML trang danh sách để kiểm tra — xem dòng ⓘ ở trên.")
            self.log(f"JobsGO: tìm thấy {self._total_count:,} lượt ứng tuyển "
                     f"trên {self._last_page:,} trang.")
        except (LoginError, ChromeStartError):
            raise
        except Exception as exc:
            raise LoginError(f"Lỗi kết nối JobsGO: {str(exc)[:160]}")

    # ---------------------------------------------------------------- danh sách
    def _goto_list_page(self, page):
        url = f"{LIST_URL}?page={int(page)}&per-page={PAGE_SIZE}"
        safe_get(self.driver, url, 1.0)
        self._wait_list_dom(seconds=15)
        return self._html()

    @staticmethod
    def _parse_total(html, item_count):
        soup = BeautifulSoup(html or "", "html.parser")
        text = soup.get_text(" ", strip=True)
        found = [int(m.group(1).replace(".", "").replace(",", ""))
                 for m in re.finditer(r"([\d.,]+)\s*Ứng viên", text, re.I)]
        plausible = [n for n in found if n >= item_count]
        if plausible:
            return max(plausible)
        return item_count

    @staticmethod
    def _candidate_ids(href):
        """`cid`/`jid` qua parse_qs (không giả định thứ tự tham số trong URL)."""
        query = parse_qs(urlparse(href).query)
        cid = query.get("cid", [""])[0]
        jid = query.get("jid", [""])[0]
        return cid, jid

    def _parse_items(self, html):
        soup = BeautifulSoup(html or "", "html.parser")
        if soup.select_one("input[type='password']") and not soup.select_one("a.candidate-name-link"):
            return []

        # QUAN TRỌNG: ứng viên được NHÓM theo tin tuyển dụng - link job (class
        # "text-grey text-bold") xuất hiện MỘT LẦN trước cả cụm ứng viên ứng
        # tuyển vào tin đó, không phải anh em cùng khối với từng dòng ứng viên.
        # Vì vậy phải duyệt toàn trang THEO ĐÚNG THỨ TỰ DOM và nhớ "tin đang xét",
        # thay vì leo cha từ mỗi link ứng viên (leo cha từng dòng bỏ sót vị trí -
        # đã kiểm chứng thực tế: 3/3 hồ sơ mẫu có "position" rỗng trước khi sửa).
        seen, items = set(), []
        current_position, current_campaign = "", ""
        for el in soup.find_all("a", href=True):
            classes = el.get("class") or []
            href = el["href"]
            if "candidate-name-link" not in classes:
                if "text-grey" in classes and "text-bold" in classes and "/job/detail/" in href:
                    match = re.search(r"/job/detail/(\d+)", href)
                    current_campaign = match.group(1) if match else ""
                    current_position = el.get_text(" ", strip=True)
                continue

            cid, jid = self._candidate_ids(href)
            if not cid or not jid:
                continue
            cv_id = f"{cid}-{jid}"
            if cv_id in seen:
                continue
            seen.add(cv_id)

            row = el
            for _ in range(6):
                row = row.parent
                if row is None or row.name in ("body", "html"):
                    row = el
                    break
                if len(row.get_text(" ", strip=True)) > 60:
                    break
            text = row.get_text(" ", strip=True) if row else el.get_text(" ", strip=True)

            name = el.get_text(" ", strip=True) or f"Ứng viên {cv_id}"
            email = re.search(r"[\w.%+\-]+@[\w.\-]+\.[A-Za-z]{2,}", text)
            # HOẶC dãy số liền nhau, HOẶC số chia nhóm bằng đúng 1 dấu cách/gạch
            # giữa các nhóm ≥2 chữ số ("090 123 4567") — không dùng lớp ký tự
            # gộp chung số+dấu cách: kiểu đó từng nuốt nhầm chữ số của nhãn "N
            # file" (số file đính kèm) đứng ngay sau số điện thoại vào cuối số
            # điện thoại. Xem memory edge-dom-text-regex-swallow-bug.
            phone = re.search(
                r"(?<!\d)(?:\+?84|0)(?:\d{8,10}|\d{2,4}(?:[ .\-]\d{2,4}){1,3})(?!\d)", text)
            has_file = bool(row and row.select_one("a.files-link")) if row else False

            items.append({
                "source": self.key, "account": self.email, "cv_id": cv_id,
                "fullname": name,
                "email": email.group(0).lower() if email else "",
                "phone": re.sub(r"[^\d+]", "", phone.group(0)) if phone else "",
                "position": current_position,
                # `jid` (mã tin, đã mã hoá) luôn có trong href kể cả khi không
                # đọc được link tiêu đề tin phía trên cụm — vẫn nhóm được ứng
                # viên theo tin đã ứng tuyển. Ưu tiên mã tin đọc từ link tiêu đề.
                "campaign_id": current_campaign or jid,
                "applied_at": "", "applied_ts": "",
                "apply_source": "JobsGO", "status": "Applied",
                "cv_url": urljoin(WEB, href),
                # Chỉ mang tính tham khảo (hiển thị) — KHÔNG dùng để quyết định
                # có thử tải hay không. Một hồ sơ "0 file" (chưa tải CV lên)
                # vẫn có thể có nút "Tải xuống" xuất CV được tạo từ chính dữ
                # liệu đã khai trực tiếp trên hồ sơ (giống VietnamWorks) — đã
                # xác nhận thật trên tài khoản MSB: bỏ qua các hồ sơ này theo
                # cờ này từng báo sai "chưa đính kèm CV".
                "_has_file": has_file,
            })
        return items

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
            html = self._goto_list_page(page)
            items = self._parse_items(html)
            if not items:
                raise RuntimeError(
                    f"Trang JobsGO {page} không có dữ liệu; đã dừng để tránh checkpoint sai.")
            yield page, items

    # ---------------------------------------------------------------- tải CV
    #: Thứ tự ưu tiên nút "Tải xuống" trên trang chi tiết. `.btn-download-cv`
    #: (CV chính - tải lên hoặc tự xuất từ hồ sơ khai trực tiếp) đứng trước;
    #: một hồ sơ có thể có NHIỀU nút (đã gặp thật: ứng viên có "CV đã tải lên
    #: 3" kèm cả nút CV tự xuất) — link ở host `admin.jobsgo.vn/uploads/
    #: external_candidate/...` đôi khi trả 403 dù link `jobsgo.vn/uploads/...`
    #: trên CÙNG trang lại tải được bình thường, nên phải thử LẦN LƯỢT tất cả,
    #: không dừng lại ở link đầu tiên.
    DOWNLOAD_BUTTON_SELECTORS = (
        "a.btn-download-cv[href]", "a.btn-download[href]", 'a[href^="/tool/download"]')

    @classmethod
    def _extract_cdn_urls(cls, html):
        """Mọi link CDN thô giải mã được từ các nút 'Tải xuống' trên trang,
        theo đúng thứ tự ưu tiên, không trùng lặp."""
        soup = BeautifulSoup(html or "", "html.parser")
        seen, urls = set(), []
        for selector in cls.DOWNLOAD_BUTTON_SELECTORS:
            for node in soup.select(selector):
                query = parse_qs(urlparse(node["href"]).query)
                values = query.get("l")
                if not values:
                    continue
                url = unquote(values[0])
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
        return urls

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            net.apply(session, self.cfg)
            session.headers.update({"User-Agent": "Mozilla/5.0"})
            self._local.session = session
        return session

    def _wait_download_buttons(self, seconds=25):
        """Chờ trang chi tiết dựng xong VÀ chờ nút "Tải xuống" có href THẬT —
        không chỉ chờ phần tử tồn tại trong DOM.

        Với hồ sơ khai trực tiếp trên form (không có file tải lên), nút
        `.btn-download-cv` đã nằm sẵn trong HTML ngay từ đầu nhưng href chỉ là
        placeholder "#" — trang tự gọi AJAX `/dashboard/get-cv-file?cid=...
        &jid=...` (JobsGO xuất PDF từ dữ liệu hồ sơ phía server) rồi mới gán
        href thật (chứa "l=...") vào ĐÚNG nút đó bằng JS. Bản trước chỉ chờ
        phần tử xuất hiện (luôn đúng ngay lập tức vì nút placeholder có sẵn từ
        đầu) nên đọc HTML quá sớm — thấy nút nhưng href vẫn là "#", không
        trích được link nào, báo sai "Không tìm thấy nút 'Tải xuống'" dù hồ sơ
        vẫn tải được bình thường trên web (đã gặp thật, xem
        KINH_NGHIEM_TRIEN_KHAI_CAC_KENH_TUYEN_DUNG.md mục 37.1)."""
        deadline = time.time() + seconds
        selector = ", ".join(self.DOWNLOAD_BUTTON_SELECTORS)
        while time.time() < deadline:
            if self._on_login_page():
                return
            with self._driver_lock:
                try:
                    for el in self.driver.find_elements("css selector", selector):
                        href = el.get_attribute("href") or ""
                        if "tool/download" in href and "l=" in href:
                            return
                except Exception:
                    pass
            time.sleep(0.5)

    def _click_download_button(self, download_dir):
        """Phương án cuối: bấm thẳng nút 'Tải xuống' thật trong trình duyệt và
        bắt file qua CDP — đúng như thao tác tay, dùng khi mọi link CDN thô
        đều thất bại qua requests (vd bị chặn hotlink ở một số host).

        Một hồ sơ có thể có ĐỒNG THỜI nhiều nút khớp selector nhưng chỉ một
        vài nút thật sự hoạt động: `.btn-download-cv` có thể vẫn còn href="#"
        (placeholder chưa được JS gán, hoặc hồ sơ này vốn dùng nút
        `.btn-download` khác để tải file đã upload) trong khi `.btn-download`
        cùng lúc đó đã có href thật trỏ `/tool/download?...`. Bấm nhầm nút
        href="#" sẽ không tải gì cả rồi chờ hết 30 giây vô ích — đã gặp thật.
        Phải lọc theo href thật (chứa "tool/download"), không chỉ theo
        selector khớp đầu tiên."""
        with self._driver_lock:
            try:
                self.driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                    "behavior": "allow", "downloadPath": download_dir})
            except Exception:
                pass
            button = None
            for selector in self.DOWNLOAD_BUTTON_SELECTORS:
                for candidate in self.driver.find_elements("css selector", selector):
                    if not candidate.is_displayed():
                        continue
                    if "tool/download" not in (candidate.get_attribute("href") or ""):
                        continue
                    button = candidate
                    break
                if button is not None:
                    break
            if button is None:
                return False
            try:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});arguments[0].click();", button)
            except Exception:
                return False
        deadline = time.time() + 30
        while time.time() < deadline:
            names = [n for n in os.listdir(download_dir) if not n.endswith((".crdownload", ".tmp"))]
            if names:
                return True
            time.sleep(0.5)
        return False

    def _apply_detail_fields(self, item, html):
        """Điền các trường chỉ có trên trang chi tiết vào item (chỉ khi trống)."""
        for key, value in self._parse_detail_fields(html).items():
            if value and not item.get(key):
                item[key] = value
        item["detail_loaded"] = 1

    def enrich(self, item):
        """Engine gọi cho hồ sơ cũ (đã tải CV, chưa detail_loaded) khi chạy
        "Tải tất cả" - chỉ mở trang chi tiết để lấy thêm dữ liệu, không tải lại
        file. Lỗi phải ném ra để engine ghi nhận, KHÔNG nuốt."""
        detail_url = item.get("cv_url")
        if not detail_url:
            return
        with self._driver_lock:
            safe_get(self.driver, detail_url, 1.2)
            if self._on_login_page():
                raise LoginError("Phiên JobsGO đã hết hạn. Hãy đăng nhập lại trên Chrome.")
        self._wait_download_buttons()
        self._apply_detail_fields(item, self._html())

    def download(self, item_or_id):
        item = item_or_id if isinstance(item_or_id, dict) else {"cv_id": str(item_or_id)}
        detail_url = item.get("cv_url")
        if not detail_url:
            return None, "Thiếu đường dẫn hồ sơ JobsGO."

        with self._driver_lock:
            try:
                safe_get(self.driver, detail_url, 1.4)
            except Exception as exc:
                return None, f"Không mở được trang hồ sơ JobsGO: {str(exc)[:120]}"
            if self._on_login_page():
                raise LoginError("Phiên JobsGO đã hết hạn. Hãy đăng nhập lại trên Chrome.")
        self._wait_download_buttons()
        html = self._html()

        # Trang chi tiết ĐÃ mở sẵn ở đây để tìm nút tải - tiện thể bóc luôn các
        # trường chỉ có trên trang chi tiết (không có trong danh sách), nhất là
        # "Làm việc tại" = nơi làm việc mong muốn. Chỉ điền khi item chưa có.
        if isinstance(item_or_id, dict):
            self._apply_detail_fields(item, html)

        cdn_urls = self._extract_cdn_urls(html)
        if not cdn_urls:
            return None, "Không tìm thấy nút 'Tải xuống' trên trang hồ sơ JobsGO."

        last_error = ""
        for cdn_url in cdn_urls:
            try:
                response = self._session().get(cdn_url, timeout=90)
            except requests.RequestException as exc:
                last_error = f"lỗi kết nối ({str(exc)[:100]})"
                continue
            if response.status_code != 200 or not response.content:
                last_error = f"HTTP {response.status_code}"
                continue
            ext = sniff_ext(response.content) or response_ext(response)
            if not ext:
                last_error = "nội dung không phải file CV hợp lệ"
                continue
            return response.content, ext

        # Mọi link CDN thô đều thất bại (vd bị chặn hotlink ở một host cụ thể) -
        # bấm thẳng nút thật trong trình duyệt, đúng như thao tác tay.
        folder = tempfile.mkdtemp(prefix="msbradar-jobsgo-")
        try:
            if self._click_download_button(folder):
                names = [n for n in os.listdir(folder) if not n.endswith((".crdownload", ".tmp"))]
                if names:
                    path = os.path.join(folder, names[0])
                    with open(path, "rb") as handle:
                        data = handle.read()
                    ext = sniff_ext(data) or ("." + names[0].rsplit(".", 1)[-1] if "." in names[0] else None)
                    if data and ext:
                        return data, ext
        finally:
            shutil.rmtree(folder, ignore_errors=True)

        return None, f"Không tải được CV JobsGO qua mọi đường đã thử ({last_error or 'không rõ lý do'})."

    #: Nhãn ở mục "Thông Tin Cơ Bản" của trang chi tiết JobsGO -> cột DB.
    #: "Làm việc tại" chính là nơi làm việc mong muốn (JobsGO gọi kiểu này,
    #: khác hẳn "Nơi làm việc mong muốn" của VietnamWorks hay "Địa điểm" của
    #: CareerViet - xem KINH_NGHIEM_TRIEN_KHAI_CAC_KENH_TUYEN_DUNG.md mục 41).
    _LABEL_TO_FIELD = {
        "Làm việc tại": "desired_location",
        "Địa chỉ": "address",
        "Năm sinh": "birth_year",
        "Giới tính": "gender",
    }
    _EMPTY_VALUES = ("", "-", "chưa cập nhật", "không có", "n/a", "đang cập nhật",
                     "chưa có thông tin", "chưa có thông tin học vấn",
                     "chưa có thông tin kinh nghiệm")

    @classmethod
    def _parse_detail_fields(cls, html):
        """Bóc các trường chỉ có trên trang chi tiết.

        - Mục 'Thông Tin Cơ Bản': mỗi cặp là `<li><strong>Nhãn:</strong>
          <span>giá trị</span></li>` (đã kiểm chứng 5/5 hồ sơ mẫu) — lấy đúng
          `<span>` anh em ngay sau `<strong>`, không quét text cả trang.
        - `.candidate-position` ở header hồ sơ: VỊ TRÍ ỨNG TUYỂN — nằm ngoài
          mục 'Thông Tin Cơ Bản' nên vòng `<strong>` không chạm tới. Đây là
          nguồn `position` tin cậy nhất (link tiêu đề tin ở trang danh sách
          hay đổi cấu trúc; 2026-09 đã thấy 0/43 hồ sơ lấy được từ danh sách).
        - `#tab-qua-trinh .resume-item` đầu tiên: chức danh + công ty gần nhất.
        - `#tab-hoc-van .resume-item` đầu tiên: học vấn (bỏ placeholder)."""
        soup = BeautifulSoup(html or "", "html.parser")
        out = {}

        pos = soup.select_one(".candidate-position")
        if pos is not None:
            value = pos.get_text(" ", strip=True).strip(" :·|-,")
            if value and value.lower() not in cls._EMPTY_VALUES:
                out["position"] = value[:150]

        work = soup.select_one("#tab-qua-trinh .resume-item")
        if work is not None:
            title_el = work.find(["h4", "h3"])
            company_el = work.find("small")
            title = (title_el.get_text(" ", strip=True) if title_el else "").strip(" :·|-,")
            company = (company_el.get_text(" ", strip=True) if company_el else "").strip(" :·|-,")
            if title and title.lower() not in cls._EMPTY_VALUES:
                out["current_title"] = title[:120]
            if company and company.lower() not in cls._EMPTY_VALUES:
                out["last_company"] = company[:120]

        edu = soup.select_one("#tab-hoc-van .resume-item")
        if edu is not None:
            parts = [p.get_text(" ", strip=True)
                     for p in edu.find_all(["h4", "h3", "small"])]
            value = " — ".join(p for p in parts if p).strip(" :·|-,")
            if value and value.lower() not in cls._EMPTY_VALUES:
                out["education"] = value[:150]

        for strong in soup.find_all("strong"):
            label = strong.get_text(" ", strip=True).rstrip(":").strip()
            field = cls._LABEL_TO_FIELD.get(label)
            if not field or field in out:
                continue
            sibling = strong.find_next_sibling()
            if sibling is not None and sibling.name == "span":
                value = sibling.get_text(" ", strip=True)
            else:
                nxt = strong.next_sibling
                value = nxt.strip() if isinstance(nxt, str) else ""
            value = value.strip(" :·|-,")
            if field == "birth_year":
                year = re.search(r"(19|20)\d{2}", value)
                value = year.group(0) if year else ""
            elif field == "desired_location":
                from ..geo import normalize_location
                value = normalize_location(value)
            if value and value.lower() not in cls._EMPTY_VALUES:
                out[field] = value[:120]
        return out

    # ---------------------------------------------------------------- misc
    def _dump_debug(self, html):
        if self._dumped:
            return
        self._dumped = True
        try:
            path = os.path.join(local_state_dir(), "jobsgo_list_dump.html")
            with open(path, "w", encoding="utf-8", errors="replace") as handle:
                handle.write(html or "")
            self.log(f"  ⓘ Đã lưu trang danh sách JobsGO để đối chiếu: {path}")
        except Exception as exc:
            self.log(f"  ! Không ghi được jobsgo_list_dump.html: {str(exc)[:120]}")

    def close(self):
        session = getattr(self._local, "session", None)
        if session:
            try:
                session.close()
            except Exception:
                pass
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
