# -*- coding: utf-8 -*-
"""Provider VietnamWorks Employer - ứng viên được phân nhóm theo từng vị trí tuyển dụng."""
import math
import os
import json
import base64
import random
import re
import shutil
import threading
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup

from ..browser import start_driver, safe_get, bring_to_front
from .base import Provider, LoginError
from ..config import account_for_source
from .topcv import sniff_ext, response_ext
from .. import net


WEB = "https://employer.vietnamworks.com"
CANDIDATES_URL = f"{WEB}/job/v3/candidates"
JOB_INDEX_URL = f"{WEB}/v2/job/default/index"
LOGIN_URL = f"{WEB}/v2/login/"
GRAPHQL = "https://ms.vietnamworks.com/job-application/graphql"
JOB_LIST_GRAPHQL = "https://ms.vietnamworks.com/job-list/graphql"
PAGE_SIZE = 20

JOB_LIST_QUERY = """
query search($type: String!, $page: Float!, $time: Float) {
  jobList(type: $type, page: $page, time: $time) {
    total
    data {
      jobId jobTitle createdOn isOnline
      extraInfo { totalApplication numOfApplications unreadApplication approvedDate status showCandidate }
    }
  }
}
"""

LIST_QUERY = """
query search($jobId: Float!, $currentPage: Int, $orderBy: String, $orderType: String) {
  jobCandidates(jobId: $jobId, currentPage: $currentPage,
    orderBy: $orderBy, orderType: $orderType) {
    jobTitle noOfCandidates approvedDate
    candidates {
      applicationId email resumeId candidateId applyType jobId jobTitle expectedPosition isViewedByAMS
      mostRecentJobTitle mostRecentCompany name createdOn yearOfExperiences resumeStatusId
      experienceLabel isExternal applicationSourceName resumeStatusName jobLevelId
      expectedSalary appTypeSource jobAppType canDownload
    }
  }
}
"""

DETAIL_QUERY = """
query searchApplication($appType: Float!, $appId: Float!, $langId: Float!, $view: String!) {
  detailApplicationAction(appType: $appType, appId: $appId, langId: $langId, view: $view) {
    resumeData {
      userInfo { emailAddress firstName lastName birthday address cityName district
        homephone cellphone jobTitle }
      userInfoDegreeData { degreeName }
      applicationInfo { fileName fileMine attachmentPath attachmentFileMime attachmentFileAlias
        fullName entryId isAttached jobTitle expectedPosition jobId appliedDate resumeStatus
        appTypeSource canDownload }
      searchableResume { mostRecentJobTitle currentJobLevel highestDegreeName }
      resume { gender birthday address contactDistrict contactCity mostRecentCompany
        yearsExperienceId highestDegreeName skills { name } }
    }
    jobTitle
  }
}
"""


class VietnamWorksProvider(Provider):
    key = "vietnamworks"
    display_name = "VietnamWorks"
    website = "employer.vietnamworks.com"
    available = True
    # Ứng viên mới có thể xuất hiện ở bất kỳ vị trí nào, không chỉ job đang mở đầu tiên.
    safe_first_page_no_change = False
    scan_all_new_scope = True
    supports_detail_enrichment = True
    max_concurrency = 4
    INVALID_JOB_STOP_THRESHOLD = 30

    def __init__(self, cfg, log=print):
        super().__init__(cfg, log)
        self.driver = None
        self._token = ""
        self._cookies = {}
        self._ua = "Mozilla/5.0"
        self._local = threading.local()
        self._driver_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._throttle_lock = threading.Lock()
        self._throttle_until = 0.0
        self._next_request_at = 0.0
        self._transient_failures = 0
        self._jobs = []
        self._invalid_job_ids = set()
        self._history_cutoff_ts = 0.0
        self._tasks = []
        self._first_page_items = []
        self._total = 0
        self._last_page = 1
        self.new_scan_min_pages = 1
        self.run_mode = "moi"

    def concurrency_limit(self):
        """Full-history backup is deliberately gentler than routine new-CV scans."""
        return 2 if self.run_mode in ("tatca", "loi") else self.max_concurrency

    def minimum_item_delay_ms(self):
        return 650 if self.run_mode in ("tatca", "loi") else 250

    def minimum_page_delay_ms(self):
        return 900 if self.run_mode in ("tatca", "loi") else 400

    def _request_interval(self):
        # Shared by metadata, detail and file requests, preventing worker bursts
        # before VietnamWorks has a chance to respond with HTTP 429.
        return 0.30 if self.run_mode in ("tatca", "loi") else 0.10

    @staticmethod
    def _catalog_path():
        from ..state_paths import local_state_dir
        folder = local_state_dir()
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "vietnamworks_job_catalog.json")

    def _load_catalog(self):
        try:
            with open(self._catalog_path(), encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data.get("jobs"), dict):
                return data
        except Exception:
            pass
        return {"jobs": {}, "expired_complete": False}

    def _save_catalog(self, catalog):
        path = self._catalog_path()
        temp = path + ".part"
        catalog["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(catalog, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(temp, path)

    @staticmethod
    def _job_created_ts(value):
        """Comparable timestamp for VietnamWorks epoch seconds/ms and ISO dates."""
        if isinstance(value, dict):
            value = value.get("createdDate")
        raw = str(value or "").strip()
        if not raw:
            return 0.0
        try:
            number = float(raw)
            if number > 100_000_000_000:
                number /= 1000.0
            return number if number > 0 else 0.0
        except (TypeError, ValueError):
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            return 0.0

    def _save_history_cutoff(self, timestamp):
        if timestamp <= 0:
            return
        catalog = self._load_catalog()
        previous = float(catalog.get("history_cutoff_ts") or 0)
        catalog["history_cutoff_ts"] = max(previous, float(timestamp))
        self._history_cutoff_ts = catalog["history_cutoff_ts"]
        self._save_catalog(catalog)

    @staticmethod
    def _normalize_job(row, status):
        extra = row.get("extraInfo") or {}
        total = max(int(extra.get("totalApplication") or 0),
                    int(extra.get("numOfApplications") or 0))
        return {
            "id": str(row.get("jobId") or ""),
            "title": row.get("jobTitle") or "",
            "createdDate": row.get("createdOn") or extra.get("approvedDate") or "",
            "totalApplication": total,
            "job_status": status,
        }

    def _job_list_page(self, status, page, time_filter=0):
        result = self._graphql(
            JOB_LIST_QUERY,
            {"type": status, "page": float(page), "time": float(time_filter)},
            operation_name="search", endpoint=JOB_LIST_GRAPHQL)
        return result.get("jobList") or {}

    def _scan_job_type(self, status, time_filter=0, known=None, full=True, max_pages=None):
        """Fetch one legacy job tab; expired history may stop after stable cached pages."""
        first = self._job_list_page(status, 1, time_filter)
        rows = list(first.get("data") or [])
        total = int(first.get("total") or 0)
        page_size = max(1, len(rows))
        pages = math.ceil(total / page_size) if total else 0
        truncated = bool(max_pages and pages > max_pages)
        if max_pages:
            pages = min(pages, max_pages)
        if pages <= 1:
            return rows, total, not truncated

        if not full:
            known = known or {}
            stable = int(bool(rows) and all(str(x.get("jobId")) in known for x in rows))
            for page in range(2, pages + 1):
                page_rows = list(self._job_list_page(status, page, time_filter).get("data") or [])
                rows.extend(page_rows)
                if page_rows and all(str(x.get("jobId")) in known for x in page_rows):
                    stable += 1
                else:
                    stable = 0
                if stable >= 3:
                    return rows, total, False
            return rows, total, not truncated

        if status == "expired":
            self.log(f"Đang lập catalog lịch sử VietnamWorks: {total:,} job hết hạn "
                     f"trên {pages:,} trang metadata...")

        def fetch(page):
            return page, list(self._job_list_page(status, page, time_filter).get("data") or [])

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(fetch, page) for page in range(2, pages + 1)]
            page_data = {}
            failed_pages = 0
            completed_pages = 1
            for future in as_completed(futures):
                try:
                    page, values = future.result()
                    page_data[page] = values
                except Exception as exc:
                    failed_pages += 1
                    self.log(f"  ! Chưa đọc được một trang job {status}: {str(exc)[:100]}")
                completed_pages += 1
                if status == "expired" and (completed_pages % 20 == 0 or completed_pages == pages):
                    self.log(f"  Catalog job hết hạn: {completed_pages:,}/{pages:,} trang metadata.")
        for page in range(2, pages + 1):
            rows.extend(page_data.get(page, []))
        return rows, total, failed_pages == 0 and not truncated

    def _discover_jobs(self, legacy_jobs):
        cached = self._load_catalog()
        self._history_cutoff_ts = float(cached.get("history_cutoff_ts") or 0)
        full_expired = self.run_mode == "tatca"
        catalog_incomplete = not cached.get("expired_complete")
        catalog = {} if full_expired else dict(cached.get("jobs") or {})
        # Older builds used the invalid type "virtualJob". VietnamWorks then
        # returned public marketplace jobs (often 10,000 rows) instead of this
        # employer's empty "virtual-job" tab. Never reuse that polluted cache.
        catalog = {job_id: job for job_id, job in catalog.items()
                   if job.get("job_status") != "virtualJob"}
        scanned_counts = {}
        discovery_failed = False

        # Active/small tabs are cheap and always refreshed. expiry7day overlaps online,
        # but querying both protects against VietnamWorks changing the online filter.
        for status, time_filter in (("online", 0), ("expiry7day", 0),
                                    ("inactive", 0), ("draft", 0), ("virtual-job", 0)):
            try:
                rows, total, _ = self._scan_job_type(status, time_filter, full=True)
            except Exception as exc:
                self.log(f"  ! Không đọc được tab job {status}: {str(exc)[:120]}")
                rows, total = [], 0
                discovery_failed = True
            scanned_counts[status] = total
            if status == "online" and not full_expired:
                active_ids = {str(x.get("jobId")) for x in rows}
                for job in catalog.values():
                    if job.get("job_status") in ("online", "expiry7day") and job.get("id") not in active_ids:
                        job["job_status"] = "expired_cached"
            for row in rows:
                job = self._normalize_job(row, status)
                if job["id"]:
                    catalog[job["id"]] = job

        try:
            expired_rows, expired_total, expired_finished = self._scan_job_type(
                "expired", 5, known=catalog, full=full_expired,
                max_pages=5 if catalog_incomplete and not full_expired else None)
        except Exception as exc:
            self.log(f"  ! Không đọc được tab job expired, dùng danh mục gần nhất: {str(exc)[:120]}")
            expired_rows, expired_total, expired_finished = [], 0, False
            discovery_failed = True
        scanned_counts["expired"] = expired_total
        for row in expired_rows:
            job = self._normalize_job(row, "expired")
            if job["id"]:
                catalog[job["id"]] = job
        if full_expired and (not expired_finished or discovery_failed):
            for job_id, job in (cached.get("jobs") or {}).items():
                catalog.setdefault(job_id, job)

        # Keep /api/my-job as a compatibility fallback for jobs temporarily absent
        # from the legacy GraphQL index.
        for row in legacy_jobs:
            job_id = str(row.get("id") or "")
            if job_id and job_id not in catalog:
                catalog[job_id] = {
                    "id": job_id, "title": row.get("title") or "",
                    "createdDate": row.get("createdDate") or "",
                    "totalApplication": int(row.get("totalApplication") or 0),
                    "job_status": "legacy_api",
                }

        result = {
            "jobs": catalog,
            "history_cutoff_ts": self._history_cutoff_ts,
            "expired_complete": bool(
                (full_expired and expired_finished and not discovery_failed)
                or (not full_expired and cached.get("expired_complete"))),
            "tab_counts": scanned_counts,
        }
        self._save_catalog(result)
        if not result["expired_complete"] and not full_expired:
            self.log("  ! Danh mục job hết hạn chưa đầy đủ. Hãy chạy 'Tải tất cả' một lần "
                     "để lập catalog lịch sử; các lượt 'CV mới' sau đó sẽ chỉ kiểm tra phần thay đổi.")
        positive = [x for x in catalog.values() if int(x.get("totalApplication") or 0) > 0]
        self.log("Đã hợp nhất danh mục VietnamWorks: "
                 + ", ".join(f"{key} {value:,}" for key, value in scanned_counts.items())
                 + f" · {len(positive):,} vị trí có hồ sơ.")
        return positive

    def _browser_cfg(self):
        return SimpleNamespace(
            # VietnamWorks trả 403 cho Chrome headless (mục 15) - KHÔNG cho chạy
            # ẩn dù cờ toàn cục `headless` đang bật.
            headless=False,
            chrome_version=getattr(self.cfg, "chrome_version", 0),
            chromedriver_path=getattr(self.cfg, "chromedriver_path", ""),
            proxy_url=getattr(self.cfg, "proxy_url", ""),
            profile_dir=self.cfg.vietnamworks_profile_dir,
        )

    def _read_session(self):
        cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
        token = cookies.get("ONB_JWT") or ""
        if not token:
            return False
        self._token = token
        self._cookies = cookies
        self._ua = self.driver.execute_script("return navigator.userAgent") or self._ua
        self._local = threading.local()
        return True

    def _wait_login(self, minutes=5, reject_token=""):
        deadline = time.time() + minutes * 60
        bring_to_front(self.driver)
        self.log("VietnamWorks cần đăng nhập/xác minh trên Chrome. Phần mềm sẽ tự chạy tiếp khi hoàn tất.")
        while time.time() < deadline:
            if "/login" not in self.driver.current_url.lower() and self._read_session():
                if not reject_token or self._token != reject_token:
                    return
            time.sleep(2)
        raise LoginError("Hết thời gian chờ đăng nhập VietnamWorks. Hãy đăng nhập trên cửa sổ Chrome rồi thử lại.")

    def _login(self):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException

        safe_get(self.driver, LOGIN_URL, 2)
        try:
            email = WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.NAME, "email")))
            password = self.driver.find_element(By.NAME, "password")
            email.clear()
            email.send_keys(self.cfg.vietnamworks_email)
            password.clear()
            password.send_keys(self.cfg.vietnamworks_password)
            # Form hiện dùng state phía client; send_keys có lúc thay được DOM value
            # nhưng validation chưa nhận state. Phát đủ các event như thao tác thật.
            for element in (email, password):
                self.driver.execute_script("""
                    for (const name of ['input', 'change', 'blur']) {
                      arguments[0].dispatchEvent(new Event(name, {bubbles: true}));
                    }
                """, element)
            remember = self.driver.find_elements(By.NAME, "rememberMe")
            if remember and not remember[0].is_selected():
                self.driver.execute_script("arguments[0].click()", remember[0])
            selector = "button[type='submit'].btn-page"
            submit = WebDriverWait(self.driver, 15).until(
                lambda driver: next((button for button in driver.find_elements(
                    By.CSS_SELECTOR, selector)
                    if button.is_displayed() and button.is_enabled()
                    and button.get_attribute("disabled") is None), False))
            try:
                submit.click()
            except ElementClickInterceptedException:
                # Chỉ fallback khi nút đã enabled; không cưỡng ép nút disabled.
                self.driver.execute_script("arguments[0].click()", submit)
        except TimeoutException:
            self.log("Form VietnamWorks chưa bật nút đăng nhập. Hãy kiểm tra thông tin "
                     "và đăng nhập thủ công trên cửa sổ Chrome đang mở.")
            self._wait_login()
            return
        except Exception as e:
            # Website có thể đổi form/cookie banner. Giữ Chrome mở để người dùng xử
            # lý hợp lệ thay vì kết thúc toàn bộ lượt đồng bộ ngay lập tức.
            self.log(f"Không tự thao tác được form VietnamWorks ({str(e)[:100]}). "
                     "Chuyển sang chờ đăng nhập thủ công.")
            self._wait_login()
            return

        for _ in range(15):
            if "/login" not in self.driver.current_url.lower() and self._read_session():
                return
            time.sleep(1)
        self._wait_login()

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None or getattr(self._local, "token", None) != self._token:
            session = requests.Session()
            net.apply(session, self.cfg)
            session.headers.update({
                "User-Agent": self._ua,
                "Referer": CANDIDATES_URL,
                "Accept": "application/json, text/plain, */*",
            })
            for name, value in self._cookies.items():
                session.cookies.set(name, value)
            self._local.session = session
            self._local.token = self._token
        return session

    @staticmethod
    def _trusted_auth_url(url):
        host = (urlparse(str(url)).hostname or "").lower()
        return host in {"employer.vietnamworks.com", "ms.vietnamworks.com"}

    def _refresh_session(self, rejected_token=""):
        """Refresh cookie/Bearer once when concurrent workers see an expired session."""
        with self._refresh_lock:
            if rejected_token and self._token and self._token != rejected_token:
                return
            if self.driver is None:
                raise LoginError("Phiên VietnamWorks đã hết hạn. Hãy đăng nhập lại.")
            self.log("Đang làm mới phiên VietnamWorks...")
            with self._driver_lock:
                safe_get(self.driver, JOB_INDEX_URL, 3)
                has_session = self._read_session()
                if ("/login" in self.driver.current_url.lower()
                        or not has_session or self._token == rejected_token):
                    self._login()
                    safe_get(self.driver, JOB_INDEX_URL, 3)
                if self._read_session() and self._token != rejected_token:
                    return
            self._wait_login(reject_token=rejected_token)

    @staticmethod
    def _retry_delay(response, attempt):
        retry_after = (response.headers.get("Retry-After") or "").strip()
        try:
            return min(60.0, max(0.5, float(retry_after)))
        except (TypeError, ValueError):
            return min(30.0, (2 ** attempt) + random.uniform(0.25, 1.25))

    def _wait_throttle(self):
        with self._throttle_lock:
            now = time.monotonic()
            ready_at = max(self._throttle_until, self._next_request_at)
            wait = ready_at - now
            interval = self.jitter_delay(
                self._request_interval(), self.request_jitter_ratio)
            self._next_request_at = max(now, ready_at) + interval
        if wait > 0:
            time.sleep(min(wait, 60))

    def _request(self, method, url, **kwargs):
        last = None
        rejected_token = ""
        request_headers = dict(kwargs.pop("headers", {}) or {})
        for attempt in range(4):
            self._wait_throttle()
            try:
                headers = dict(request_headers)
                if self._trusted_auth_url(url):
                    headers["Authorization"] = "Bearer " + self._token
                response = self._session().request(
                    method, url, timeout=90, headers=headers, **kwargs)
                if response.status_code == 401 and self._trusted_auth_url(url):
                    rejected_token = rejected_token or self._token
                    self._refresh_session(rejected_token)
                    continue
                if response.status_code in (408, 429, 502, 503, 504):
                    last = f"HTTP {response.status_code}"
                    delay = self._retry_delay(response, attempt)
                    with self._throttle_lock:
                        self._transient_failures += 1
                        # Shared circuit-breaker: all workers slow down together instead of
                        # continuing to hammer the service after repeated throttling/outages.
                        penalty = min(60.0, delay + max(0, self._transient_failures - 2) * 2)
                        self._throttle_until = max(
                            self._throttle_until, time.monotonic() + penalty)
                    time.sleep(delay)
                    continue
                with self._throttle_lock:
                    self._transient_failures = 0
                return response
            except LoginError:
                raise
            except Exception as e:
                last = str(e)[:160]
                time.sleep(min(10, 2 ** attempt) + random.uniform(0.1, 0.8))
        if rejected_token:
            raise LoginError("Phiên VietnamWorks đã hết hạn và không thể tự làm mới. Hãy đăng nhập lại.")
        raise RuntimeError(last or "Không kết nối được VietnamWorks")

    _FETCH_SCRIPT = r"""
        var done = arguments[arguments.length - 1];
        var method = arguments[0], url = arguments[1], token = arguments[2];
        var payload = arguments[3], useAuth = arguments[4];
        var headers = {"Accept": "application/json, text/plain, */*"};
        if (useAuth && token) headers["Authorization"] = "Bearer " + token;
        if (payload !== null) headers["Content-Type"] = "application/json";
        var finished = false;
        function finish(result) {
            if (finished) return;
            finished = true; clearTimeout(timer); done(result);
        }
        var timer = setTimeout(function () { finish({status: 0, error: "timeout"}); }, 90000);
        fetch(url, {
            method: method, headers: headers, credentials: "include",
            body: payload === null ? undefined : JSON.stringify(payload)
        }).then(function (response) {
            return response.arrayBuffer().then(function (buffer) {
                var bytes = new Uint8Array(buffer), binary = "", chunk = 8192;
                for (var i = 0; i < bytes.length; i += chunk) {
                    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
                }
                finish({status: response.status, data_b64: btoa(binary)});
            });
        }).catch(function (error) {
            finish({status: 0, error: String(error)});
        });
    """

    def _browser_fetch(self, method, url, payload=None):
        """Fallback through the authenticated Chrome session."""
        if self.driver is None:
            return None, None
        try:
            with self._driver_lock:
                self.driver.set_script_timeout(95)
                result = self.driver.execute_async_script(
                    self._FETCH_SCRIPT, method, url, self._token, payload,
                    self._trusted_auth_url(url))
        except Exception:
            return None, None
        if not result or not result.get("data_b64"):
            return (result or {}).get("status"), None
        try:
            return result.get("status"), base64.b64decode(result["data_b64"])
        except Exception:
            return result.get("status"), None

    def _graphql(self, query, variables, operation_name=None, endpoint=GRAPHQL):
        payload = {"query": query, "variables": variables}
        if operation_name:
            payload["operationName"] = operation_name
        api_error = ""
        try:
            response = self._request("POST", endpoint, json=payload)
            if response.status_code == 200:
                body = response.json()
                if not body.get("errors"):
                    return body.get("data") or {}
                api_error = str(body["errors"][0].get("message", "lỗi không rõ"))[:160]
            elif response.status_code == 403:
                api_error = "HTTP 403"
            else:
                api_error = f"HTTP {response.status_code}"
        except LoginError:
            raise
        except Exception as exc:
            api_error = str(exc)[:160]

        status, raw = self._browser_fetch("POST", endpoint, payload)
        if status == 200 and raw:
            try:
                body = json.loads(raw.decode("utf-8"))
                if not body.get("errors"):
                    return body.get("data") or {}
                api_error = str(body["errors"][0].get("message", api_error))[:160]
            except Exception:
                pass
        if status == 403:
            raise RuntimeError("VietnamWorks từ chối quyền truy cập (HTTP 403). Hãy kiểm tra quyền tài khoản/công ty.")
        raise RuntimeError("VietnamWorks GraphQL: " + (api_error or f"HTTP {status or 0}"))

    @staticmethod
    def _timestamp(value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return raw[:19].replace("T", " ")

    @classmethod
    def _display_timestamp(cls, value):
        normalized = cls._timestamp(value)
        try:
            return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError):
            return normalized

    def _normalize(self, candidate, job):
        application_id = str(candidate.get("applicationId"))
        app_type = 1.0
        for raw_type in (candidate.get("jobAppType"), candidate.get("applyType")):
            try:
                if raw_type is not None and str(raw_type).strip() != "":
                    app_type = float(raw_type)
                    break
            except (TypeError, ValueError):
                continue
        return {
            "source": self.key,
            "account": account_for_source(self.cfg, self.key),
            "cv_id": application_id,
            "fullname": candidate.get("name") or "",
            "email": candidate.get("email") or "",
            "phone": "",
            "position": candidate.get("jobTitle") or job.get("title") or "",
            "campaign_id": str(candidate.get("jobId") or job.get("id") or ""),
            "applied_at": self._display_timestamp(candidate.get("createdOn")),
            "applied_ts": self._timestamp(candidate.get("createdOn")),
            "apply_source": candidate.get("applicationSourceName") or "VietnamWorks",
            "status": candidate.get("resumeStatusName") or "",
            "experience": candidate.get("experienceLabel") or str(candidate.get("yearOfExperiences") or ""),
            "years_experience": str(candidate.get("yearOfExperiences") or ""),
            "last_company": candidate.get("mostRecentCompany") or "",
            "current_title": candidate.get("mostRecentJobTitle") or candidate.get("expectedPosition") or "",
            "job_level": str(candidate.get("jobLevelId") or ""),
            "expected_salary": str(candidate.get("expectedSalary") or ""),
            "candidate_id": str(candidate.get("candidateId") or ""),
            "resume_id": str(candidate.get("resumeId") or ""),
            "profile_type": str(candidate.get("jobAppType") or candidate.get("appTypeSource") or ""),
            "is_viewed": 1 if candidate.get("isViewedByAMS") else 0,
            "cv_url": f"{WEB}/v3/application/detail/{job.get('id')}/{application_id}",
            "_app_type": app_type,
        }

    def _fetch_task(self, task):
        job, candidate_page = task
        job_id = str(job["id"])
        if job_id in self._invalid_job_ids:
            return []
        try:
            result = self._graphql(LIST_QUERY, {
                "jobId": float(job_id),
                "currentPage": int(candidate_page),
                "orderBy": "createdOn",
                "orderType": "DESC",
            }).get("jobCandidates") or {}
        except RuntimeError as exc:
            if "invalid job" in str(exc).lower():
                self._invalid_job_ids.add(job_id)
                self.log(f"  ! Bỏ qua job {job_id} đã bị VietnamWorks xóa/không còn hợp lệ: "
                         f"{job.get('title') or 'Không có tiêu đề'}")
                return []
            raise
        return [self._normalize(x, job) for x in (result.get("candidates") or [])]

    def connect(self):
        if self.driver is None:
            self.log("Đang khởi động Chrome cho VietnamWorks...")
            self.driver = start_driver(self._browser_cfg())
            self.log("Chrome VietnamWorks đã sẵn sàng. Đang kiểm tra phiên đăng nhập...")
        safe_get(self.driver, JOB_INDEX_URL, 3)
        if "/login" in self.driver.current_url.lower():
            self._login()
            safe_get(self.driver, JOB_INDEX_URL, 4)
        if not self._read_session():
            self._wait_login()

        self.log("Đang đọc đầy đủ danh mục từ Quản lý việc làm VietnamWorks "
                 "(đang hiển thị, sắp hết hạn, đã hết hạn và các tab còn lại)...")

        jobs_body = None
        jobs_response = self._request("GET", f"{WEB}/api/my-job")
        if jobs_response.status_code == 200:
            jobs_body = jobs_response.json()
        else:
            status, raw = self._browser_fetch("GET", f"{WEB}/api/my-job")
            if status == 200 and raw:
                try:
                    jobs_body = json.loads(raw.decode("utf-8"))
                except Exception:
                    pass
        if jobs_body is None:
            raise RuntimeError(
                f"Không lấy được danh sách việc làm VietnamWorks (HTTP {jobs_response.status_code})")
        legacy_jobs = (jobs_body.get("data") or {}).get("items") or []
        discovered_jobs = self._discover_jobs(legacy_jobs)

        def recent_or_mutable(job):
            if job.get("job_status") in ("online", "expiry7day", "inactive", "legacy_api"):
                return True
            timestamp = self._job_created_ts(job)
            return bool(timestamp and time.time() - timestamp <= 90 * 86400)

        # Full history is strictly newest-first. New-CV runs are scoped to jobs
        # that can still change, so scheduled checks never traverse old history.
        self._jobs = sorted(discovered_jobs, key=self._job_created_ts, reverse=True)
        if self.run_mode == "tatca" and self._history_cutoff_ts:
            before = len(self._jobs)
            self._jobs = [job for job in self._jobs
                          if self._job_created_ts(job) > self._history_cutoff_ts]
            omitted = before - len(self._jobs)
            if omitted:
                cutoff_date = datetime.fromtimestamp(self._history_cutoff_ts).strftime("%d/%m/%Y")
                self.log(f"Đã áp dụng mốc lịch sử {cutoff_date}: bỏ qua {omitted:,} vị trí cũ hơn.")

        priority_jobs = [job for job in self._jobs if recent_or_mutable(job)]
        task_jobs = priority_jobs if self.run_mode == "moi" else self._jobs
        self._total = sum(int(x.get("totalApplication") or 0) for x in task_jobs)
        first_pages = [(job, 1) for job in task_jobs]
        older_pages = []
        for page in range(2, 100000):
            added = False
            for job in task_jobs:
                if page <= math.ceil(int(job.get("totalApplication") or 0) / PAGE_SIZE):
                    older_pages.append((job, page))
                    added = True
            if not added:
                break
        self._tasks = first_pages + older_pages
        self._last_page = max(1, len(self._tasks))
        self.new_scan_min_pages = max(1, len(task_jobs))
        self._first_page_items = self._fetch_task(self._tasks[0]) if self._tasks else []
        scope = "có thể phát sinh hồ sơ mới" if self.run_mode == "moi" else "trong phạm vi lịch sử"
        self.log(f"Đã kết nối VietnamWorks: {len(task_jobs):,} vị trí {scope}, "
                 f"{self._total:,} lượt ứng tuyển · thứ tự mới nhất đến cũ nhất.")

    def total_count(self):
        return self._total

    @property
    def last_page(self):
        return self._last_page

    def peek_first_page(self):
        return self._first_page_items

    def range_total(self, start_page=1, end_page=None):
        """Return the exact candidate count for a virtual-page range."""
        end_page = min(int(end_page or self._last_page), self._last_page)
        start_page = max(1, int(start_page))
        total = 0
        for job, candidate_page in self._tasks[start_page - 1:end_page]:
            remaining = int(job.get("totalApplication") or 0) - (candidate_page - 1) * PAGE_SIZE
            total += max(0, min(PAGE_SIZE, remaining))
        return total

    def iter_pages(self, start_page=1, end_page=None, reverse=False):
        end_page = min(int(end_page or self._last_page), self._last_page)
        pages = list(range(max(1, int(start_page)), end_page + 1))
        if reverse:
            pages.reverse()
        invalid_streak = 0
        invalid_streak_start_ts = 0.0
        stop_on_invalid_history = self.run_mode == "tatca" and not reverse and int(start_page) == 1
        for virtual_page in pages:
            task = self._tasks[virtual_page - 1]
            items = self._first_page_items if virtual_page == 1 else self._fetch_task(task)
            job, candidate_page = task
            if stop_on_invalid_history and candidate_page == 1:
                if str(job.get("id")) in self._invalid_job_ids:
                    if invalid_streak == 0:
                        invalid_streak_start_ts = self._job_created_ts(job)
                    invalid_streak += 1
                    if invalid_streak >= self.INVALID_JOB_STOP_THRESHOLD:
                        self._save_history_cutoff(invalid_streak_start_ts)
                        self.log(
                            f"Đã gặp {self.INVALID_JOB_STOP_THRESHOLD} vị trí liên tiếp không còn hợp lệ. "
                            "Xác nhận đã tới cuối vùng dữ liệu khả dụng và dừng tải lịch sử.")
                        return
                else:
                    invalid_streak = 0
                    invalid_streak_start_ts = 0.0
            self.log(f"VietnamWorks · vị trí {job.get('title', '')} · trang ứng viên {candidate_page}")
            yield virtual_page, items

    def iter_reconciliation(self, depth=2):
        """Recheck newest pages after a long full run to catch pagination drift."""
        for job in self._jobs:
            page_count = math.ceil(int(job.get("totalApplication") or 0) / PAGE_SIZE)
            for candidate_page in range(1, min(max(1, depth), page_count) + 1):
                yield self._fetch_task((job, candidate_page))

    def _load_detail(self, item):
        application_id = int(item["cv_id"])
        action = self._graphql(DETAIL_QUERY, {
            "appType": float(item.get("_app_type") or 1),
            "appId": float(application_id),
            "langId": 2.0,
            "view": "app-detail",
        }, operation_name="searchApplication").get("detailApplicationAction") or {}
        resume_data = action.get("resumeData") or {}
        user = resume_data.get("userInfo") or {}
        app = resume_data.get("applicationInfo") or {}
        resume = resume_data.get("resume") or {}
        searchable = resume_data.get("searchableResume") or {}
        degrees = resume_data.get("userInfoDegreeData") or []
        if isinstance(degrees, dict):
            degrees = [degrees]
        education = ", ".join(
            str(x.get("degreeName") or "").strip() for x in degrees
            if isinstance(x, dict) and x.get("degreeName"))
        skills = ", ".join(
            str(x.get("name") or "").strip() for x in (resume.get("skills") or [])
            if isinstance(x, dict) and x.get("name"))

        full_name = app.get("fullName") or " ".join(
            x for x in (user.get("firstName"), user.get("lastName")) if x)
        item.update({
            "fullname": full_name or item.get("fullname", ""),
            "email": user.get("emailAddress") or item.get("email", ""),
            "phone": user.get("cellphone") or user.get("homephone") or "",
            "position": app.get("jobTitle") or action.get("jobTitle") or item.get("position", ""),
            "applied_at": self._display_timestamp(app.get("appliedDate")) or item.get("applied_at", ""),
            "applied_ts": self._timestamp(app.get("appliedDate")) or item.get("applied_ts", ""),
            "gender": str(resume.get("gender") or ""),
            "birth_year": str((user.get("birthday") or resume.get("birthday") or ""))[:4],
            "address": user.get("address") or resume.get("address") or "",
            "city": user.get("cityName") or resume.get("contactCity") or "",
            "district": user.get("district") or resume.get("contactDistrict") or "",
            "last_company": resume.get("mostRecentCompany") or item.get("last_company", ""),
            "experience": item.get("experience") or str(resume.get("yearsExperienceId") or ""),
            "years_experience": item.get("years_experience") or str(resume.get("yearsExperienceId") or ""),
            "current_title": searchable.get("mostRecentJobTitle") or user.get("jobTitle")
                or app.get("expectedPosition") or item.get("current_title", ""),
            "job_level": str(searchable.get("currentJobLevel") or item.get("job_level", "")),
            "education": education or searchable.get("highestDegreeName")
                or resume.get("highestDegreeName") or "",
            "skills": skills,
            "candidate_id": item.get("candidate_id", ""),
            "resume_id": item.get("resume_id", ""),
            "profile_type": str(app.get("appTypeSource") or item.get("profile_type", "")),
            "attachment_name": app.get("attachmentFileAlias") or app.get("fileName") or "",
            "attachment_mime": app.get("attachmentFileMime") or app.get("fileMine") or "",
            # Giữ bản chụp dữ liệu nguồn để không mất các thuộc tính đặc thù VietnamWorks
            # chưa có cột dùng chung; trường này không đưa vào Excel mặc định.
            "source_payload": json.dumps(action, ensure_ascii=False, separators=(",", ":")),
            "detail_loaded": 1,
        })
        self._scrape_general_panel(item)
        return app

    #: Nhãn ở panel "Thông tin chung" của trang UI (server-render) -> cột DB.
    #: Query GraphQL đang dùng KHÔNG trả các trường này (đã kiểm 45 key) - phải
    #: bóc từ DOM trang `/v3/application/detail/...`. Panel hiển thị theo NGÔN
    #: NGỮ tài khoản (VI hoặc EN — đã gặp thật cả hai), nên phải map cả hai; key
    #: đã hạ chữ thường, tra cũng hạ chữ thường. "Martial status" là lỗi chính
    #: tả TRÊN CHÍNH UI của VietnamWorks (đúng ra là "Marital"). Xem
    #: KINH_NGHIEM_TRIEN_KHAI_CAC_KENH_TUYEN_DUNG.md mục 41.
    _PANEL_MAP = {
        "nơi làm việc mong muốn": "desired_location",
        "expected job location": "desired_location",
        "expected work location": "desired_location",
        "tình trạng hôn nhân": "marital_status",
        "marital status": "marital_status",
        "martial status": "marital_status",
        "cấp bậc mong muốn": "desired_level",
        "expected job level": "desired_level",
        "trình độ ngoại ngữ": "foreign_language",
        "languages": "foreign_language",
        "language": "foreign_language",
        "mức lương hiện tại": "current_salary",
        "current salary": "current_salary",
        "mức lương mong muốn": "expected_salary",
        "expected salary": "expected_salary",
        "cấp bậc hiện tại": "job_level",
        "current job level": "job_level",
        "bằng cấp cao nhất": "education",
        "highest education": "education",
        "số năm kinh nghiệm": "years_experience",
        "years of experience": "years_experience",
        "công ty gần đây nhất": "last_company",
        "latest company": "last_company",
        "vị trí hiện tại": "current_title",
        "current position": "current_title",
        "địa chỉ": "address",
        "home address": "address",
        "ngày sinh": "birth_year",
        "birthday": "birth_year",
        "giới tính": "gender",
        "gender": "gender",
    }
    #: Các trường trên là "mới" (GraphQL không có) -> luôn ghi đè từ panel; còn
    #: lại chỉ điền khi GraphQL để trống.
    _PANEL_ALWAYS = {"desired_location", "marital_status", "desired_level",
                     "foreign_language", "current_salary"}
    _PANEL_SKIP_VALUES = {"", "-", "_", "n/a", "na", "nhập số vào", "add number",
                          "không có", "none", "not updated", "not available",
                          "chưa cập nhật", "chưa có thông tin"}

    def _scrape_general_panel(self, item):
        """Bóc panel 'Thông tin chung' (chỉ có trên trang UI). Best-effort:
        mọi lỗi đều nuốt, KHÔNG được làm hỏng đường tải. Chạy 1 lần/hồ sơ vì
        engine chặn bằng `detail_loaded`."""
        detail_url = item.get("cv_url")
        if not detail_url or self.driver is None:
            item["detail_loaded"] = 1
            return
        html, n_blocks = "", 0
        try:
            with self._driver_lock:
                safe_get(self.driver, detail_url, 1.5)
                cur = (self.driver.current_url or "")
                if "/v2/login" in cur.lower() or "/login" in cur.lower():
                    self.log(f"  ⓘ VietnamWorks: trang chi tiết chuyển về đăng nhập ({cur[:80]}).")
                    item["detail_loaded"] = 1
                    return
                # Panel "Thông tin chung" render bất đồng bộ (React/ant-tabs).
                # PHẢI đếm phần tử DOM thật (`find_elements`), KHÔNG kiểm chuỗi
                # trong page_source: class "discriptions"/"valueContent" có mặt
                # sẵn trong bundle CSS/JS ngay từ đầu, kiểm chuỗi sẽ báo "xong"
                # trong khi React chưa render panel (đã gặp thật: bóc 0 trường).
                deadline = time.time() + 30
                clicked_tab = False
                while time.time() < deadline:
                    blocks = self.driver.find_elements(
                        "css selector", "div.discriptions, div.viewExpectedSalary")
                    n_blocks = len(blocks)
                    if n_blocks:
                        html = self.driver.page_source or ""
                        break
                    # Panel có thể nằm trong tab "Thông tin ứng viên" chưa active -
                    # thử bấm tab đó một lần.
                    if not clicked_tab and time.time() - (deadline - 30) > 4:
                        clicked_tab = True
                        for tab in self.driver.find_elements(
                                "css selector", ".ant-tabs-tab, [role='tab']"):
                            label = (tab.text or "").lower()
                            if "ứng viên" in label or "thông tin" in label or "candidate" in label:
                                try:
                                    self.driver.execute_script("arguments[0].click();", tab)
                                except Exception:       # noqa: BLE001
                                    pass
                                break
                    time.sleep(0.5)
        except Exception as exc:                          # noqa: BLE001
            self.log(f"  ⓘ VietnamWorks: lỗi khi bóc panel: {str(exc)[:120]}")
            item["detail_loaded"] = 1
            return
        if not html:
            self.log(f"  ⓘ VietnamWorks: panel 'Thông tin chung' KHÔNG dựng sau 30s "
                     f"(URL {(self.driver.current_url or '')[:90]}) — mở thẳng cv_url có thể không "
                     "render panel.")
            item["detail_loaded"] = 1
            return
        seen, labels = self._apply_general_panel(html, item)
        if item.get("desired_location"):
            self.log(f"  ⓘ VietnamWorks: panel {n_blocks} khối → nơi làm việc mong muốn "
                     f"= {item['desired_location']} ({len(seen)} trường)")
        else:
            self.log(f"  ⓘ VietnamWorks: panel {n_blocks} khối, {len(seen)} trường, KHÔNG có "
                     f"'Nơi làm việc mong muốn'. Nhãn thấy: {labels[:20]}")

    def _apply_general_panel(self, html, item):
        """Phần THUẦN: từ HTML panel → điền item. Trả (set trường đã bóc, list
        nhãn thấy) để log/ test."""
        soup = BeautifulSoup(html or "", "html.parser")
        seen = set()
        for block in soup.select("div.discriptions, div.viewExpectedSalary, div.content > div"):
            title = block.select_one(
                "div.titleContent, div.titleContentSalary, div.titleContentMobile")
            value = block.select_one(
                "div.valueContent, div.valueContentSalary, div.valueContentMobile")
            if not (title and value):
                continue
            field = self._PANEL_MAP.get(
                title.get_text(" ", strip=True).lower().rstrip(":").strip())
            if not field or field in seen:
                continue
            seen.add(field)
            text = value.get_text(" ", strip=True).strip(" -_·|")
            if text.lower() in self._PANEL_SKIP_VALUES:
                continue
            if field == "birth_year":
                match = re.search(r"(19|20)\d{2}", text)
                text = match.group(0) if match else ""
            elif field == "desired_location":
                from ..geo import normalize_location
                text = normalize_location(text)
            if text and (field in self._PANEL_ALWAYS or not item.get(field)):
                item[field] = text[:150]
        labels = [t.get_text(" ", strip=True)
                  for t in soup.select("div.discriptions div.titleContent")]
        return seen, labels

    def enrich(self, item):
        """Nạp thông tin chi tiết mà không bắt buộc tải lại file CV."""
        self._load_detail(item)
        return item

    def refresh_failed_item(self, item):
        """Làm mới đúng application id qua GraphQL chi tiết, không quét danh sách."""
        self._load_detail(item)
        return True

    def _browser_navigation_download(self, item, url, click_attachment=True):
        """Last resort for view-attach links that only work as a real browser download."""
        if self.driver is None:
            return None
        download_dir = tempfile.mkdtemp(prefix="msbradar-vnw-")
        try:
            with self._driver_lock:
                self.driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                    "behavior": "allow", "downloadPath": download_dir})
                if click_attachment:
                    detail_url = item.get("cv_url") or CANDIDATES_URL
                    safe_get(self.driver, detail_url, 3)
                    try:
                        from selenium.webdriver.common.by import By
                        links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='view-attach']")
                        if links:
                            self.driver.execute_script("arguments[0].click()", links[0])
                        else:
                            self.driver.get(url)
                    except Exception:
                        self.driver.get(url)
                else:
                    self.driver.get(url)

                deadline = time.time() + 45
                while time.time() < deadline:
                    names = [name for name in os.listdir(download_dir)
                             if not name.endswith((".crdownload", ".tmp"))]
                    if names:
                        path = os.path.join(download_dir, names[0])
                        if os.path.getsize(path) > 0:
                            with open(path, "rb") as handle:
                                return handle.read()
                    time.sleep(0.4)
        except Exception:
            return None
        finally:
            shutil.rmtree(download_dir, ignore_errors=True)
        return None

    @staticmethod
    def _system_export_url(item, app):
        """URL used by VietnamWorks' download button for form-created resumes."""
        resume_id = str(item.get("resume_id") or app.get("resumeId") or "").strip()
        application_id = str(item.get("cv_id") or app.get("entryId") or "").strip()
        app_source = str(app.get("appTypeSource") or item.get("profile_type") or "").strip()
        try:
            numeric_source = float(app_source)
            if numeric_source.is_integer():
                app_source = str(int(numeric_source))
        except (TypeError, ValueError):
            pass
        if not resume_id or not application_id or not app_source:
            return ""
        return (f"{WEB}/v2/application/download/{quote(resume_id, safe='')}/"
                f"{quote(app_source, safe='')}/{quote(application_id, safe='')}/1"
                "?source=ams_screening&application_score=null")

    @staticmethod
    def _is_attached(app):
        value = app.get("isAttached")
        if value is None:
            return bool(app.get("attachmentPath"))
        return str(value).strip().lower() not in {"", "0", "false", "none", "null"}

    def _try_download_url(self, item, url, *, click_attachment):
        """Try HTTP, in-browser fetch, then a real browser navigation for one URL."""
        if not url or not str(url).startswith("https://"):
            return None, None, "đường dẫn tải không hợp lệ", None
        api_error = ""
        response = None
        try:
            response = self._request("GET", url, headers={
                "Referer": item.get("cv_url") or CANDIDATES_URL,
                "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Upgrade-Insecure-Requests": "1",
            })
            if response.status_code != 200 or not response.content:
                api_error = f"HTTP {response.status_code}"
            else:
                raw = response.content
                ext = sniff_ext(raw)
                suspicious = raw[:512].lstrip().lower().startswith(
                    (b"<!doctype html", b"<html", b"{", b"["))
                if not suspicious:
                    ext = ext or response_ext(response)
                if ext:
                    return raw.lstrip(), ".jpg" if ext == ".jpeg" else ext, "", response.status_code
                api_error = "nội dung HTTP không phải file CV hợp lệ"
        except LoginError:
            raise
        except Exception as exc:
            api_error = str(exc)[:160]

        status, raw = self._browser_fetch("GET", url)
        if status == 200 and raw:
            ext = sniff_ext(raw)
            if ext:
                return raw.lstrip(), ext, "", status
        raw = self._browser_navigation_download(item, url, click_attachment=click_attachment)
        if raw:
            ext = sniff_ext(raw)
            if ext:
                return raw.lstrip(), ext, "", status
        return None, None, api_error or f"HTTP {status or 0}", (
            response.status_code if response is not None else status)

    def download(self, item_or_id):
        item = item_or_id if isinstance(item_or_id, dict) else {"cv_id": str(item_or_id)}
        try:
            app = self._load_detail(item)
            if not app.get("canDownload"):
                return None, "VietnamWorks không cho phép tải hồ sơ này"
            attachment_url = str(app.get("attachmentPath") or "")
            export_url = self._system_export_url(item, app)
            # Form-created resumes may still contain a stale attachmentPath that returns
            # 404. The website's own button uses the system export route in that case.
            choices = []
            if self._is_attached(app) and attachment_url:
                choices.append((attachment_url, True, "file đính kèm"))
            if export_url:
                choices.append((export_url, False, "CV do VietnamWorks xuất"))
            if attachment_url and not any(url == attachment_url for url, _, _ in choices):
                choices.append((attachment_url, True, "file đính kèm"))
            if not choices:
                return None, "Hồ sơ không có đường dẫn tải phù hợp"

            errors = []
            for url, click_attachment, label in choices:
                data, ext, error, status = self._try_download_url(
                    item, url, click_attachment=click_attachment)
                if data and ext:
                    if label == "CV do VietnamWorks xuất":
                        item["attachment_name"] = item.get("attachment_name") or (
                            f"{item.get('fullname') or item.get('resume_id') or 'CV'}.pdf")
                        item["attachment_mime"] = "application/pdf"
                    return data, ext
                errors.append(f"{label}: {error}")
                if status == 403:
                    # Keep trying the system export route: attachment CDN permission may
                    # differ even though the employer can export the online resume.
                    continue
            return None, "; ".join(errors)[:180]
        except LoginError:
            raise
        except Exception as e:
            return None, str(e)[:180]

    def close(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
