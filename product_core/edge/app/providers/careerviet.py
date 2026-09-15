"""CareerViet employer provider.

CareerViet exposes one flat, newest-first application feed.  The application
identifier is ``folder_resume_id``; ``resume_id`` may be reused when the same
person applies to more than one job.
"""
from datetime import datetime, timezone, timedelta
import base64
import json
import math
import random
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlparse

import requests

from .base import Provider, LoginError
from ..config import account_for_source
from .topcv import response_ext, sniff_ext
from ..browser import start_driver, safe_get, bring_to_front
from .. import net


WEB = "https://careerviet.vn"
MANAGER_URL = f"{WEB}/vi/employers/hrcentral/manageresume"
LOGIN_PAGE = f"{WEB}/vi/employers/login"
LOGIN_API = f"{WEB}/api/auth/employers/login"
CHECK_API = f"{WEB}/api/auth/employers/check"
REFRESH_API = f"{WEB}/api/auth/employers/refresh"
INTERNAL = "https://internal-api.careerviet.vn"
INFO_API = f"{INTERNAL}/api/v1/es/emp/employer-users/info"
LIST_API = f"{INTERNAL}/api/v1/es/emp/folder-resumes/folder-apply"
DETAIL_API = f"{INTERNAL}/api/v1/jss/emp/resumes"
PAGE_SIZE = 20


class CareerVietProvider(Provider):
    key = "careerviet"
    display_name = "CareerViet"
    website = "careerviet.vn"
    available = True
    supports_detail_enrichment = True
    safe_first_page_no_change = True
    max_concurrency = 4

    def __init__(self, cfg, log=print):
        super().__init__(cfg, log)
        self.driver = None
        self.run_mode = "moi"
        self._token = ""
        self._cookies = {}
        self._ua = "Mozilla/5.0"
        self._user_id = ""
        self._total = 0
        self._last_page = 0
        self._first_page = []
        self._local = threading.local()
        self._refresh_lock = threading.Lock()
        self._driver_lock = threading.RLock()
        self._throttle_lock = threading.Lock()
        self._next_request_at = 0.0

    def concurrency_limit(self):
        return 2 if self.run_mode in ("tatca", "loi") else 4

    def minimum_item_delay_ms(self):
        return 600 if self.run_mode in ("tatca", "loi") else 250

    def minimum_page_delay_ms(self):
        return 800 if self.run_mode in ("tatca", "loi") else 350

    def _request_interval(self):
        return 0.25 if self.run_mode in ("tatca", "loi") else 0.08

    def _browser_cfg(self):
        return SimpleNamespace(
            headless=getattr(self.cfg, "headless", False),
            chrome_version=getattr(self.cfg, "chrome_version", 0),
            chromedriver_path=getattr(self.cfg, "chromedriver_path", ""),
            proxy_url=getattr(self.cfg, "proxy_url", ""),
            profile_dir=self.cfg.careerviet_profile_dir,
        )

    def _cookie_session(self):
        session = requests.Session()
        net.apply(session, self.cfg)
        from requests.adapters import HTTPAdapter
        from urllib3.util import Retry
        retries = Retry(
            total=3,
            backoff_factor=0.4,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({"User-Agent": self._ua, "Referer": MANAGER_URL,
                                "Accept": "application/json, text/plain, */*",
                                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"})
        for name, value in self._cookies.items():
            session.cookies.set(name, value, domain=".careerviet.vn")
        return session

    @staticmethod
    def _extract_token(body):
        if not isinstance(body, dict):
            return ""
        token = body.get("token")
        if isinstance(token, dict):
            return str(token.get("accessToken") or token.get("access_token") or "")
        return str(body.get("accessToken") or body.get("access_token") or "")

    def _install_response_cookies(self, response):
        """Copy auth/refresh Set-Cookie values into requests and the persistent Chrome profile."""
        changed = False
        for cookie in response.cookies:
            self._cookies[cookie.name] = cookie.value
            changed = True
            try:
                with self._driver_lock:
                    # Selenium/Chrome may otherwise keep both `careerviet.vn` and
                    # `.careerviet.vn` variants. get_cookies() can then return the
                    # expired one last and silently overwrite the fresh value.
                    self.driver.delete_cookie(cookie.name)
                    chrome_cookie = {"name": cookie.name, "value": cookie.value,
                                     "domain": "careerviet.vn",
                                     "path": cookie.path or "/",
                                     "secure": bool(cookie.secure)}
                    if cookie.expires:
                        chrome_cookie["expiry"] = int(cookie.expires)
                    if "HttpOnly" in (cookie._rest or {}):
                        chrome_cookie["httpOnly"] = True
                    same_site = (cookie._rest or {}).get("SameSite")
                    if same_site:
                        chrome_cookie["sameSite"] = str(same_site).capitalize()
                    self.driver.add_cookie(chrome_cookie)
            except Exception:
                pass
        if changed:
            self._local = threading.local()
        return changed

    def _read_session(self):
        with self._driver_lock:
            self._cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
            self._ua = self.driver.execute_script("return navigator.userAgent") or self._ua
        try:
            response = self._cookie_session().get(CHECK_API, timeout=30)
            body = response.json() if response.status_code == 200 else {}
        except (requests.RequestException, ValueError):
            return False
        token = self._extract_token(body)
        if not token:
            return False
        self._token = str(token)
        self._local = threading.local()
        return True

    def _read_browser_check_session(self):
        """Read /check JSON already displayed by Chrome; avoids a flaky duplicate HTTP call."""
        try:
            with self._driver_lock:
                raw = self.driver.execute_script(
                    "return document.body ? document.body.innerText : ''") or ""
                body = json.loads(raw)
                cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
                ua = self.driver.execute_script("return navigator.userAgent") or self._ua
        except Exception:
            return False
        token = self._extract_token(body)
        if not token:
            return False
        self._cookies = cookies
        self._ua = ua
        self._token = token
        self._local = threading.local()
        return True

    def _login(self):
        """Authenticate without placing credentials in a URL or browser history."""
        payload = {"username": self.cfg.careerviet_email,
                   "password": self.cfg.careerviet_password}
        try:
            response = self._cookie_session().post(LOGIN_API, json=payload, timeout=45,
                                                    headers={"Origin": WEB,
                                                             "Referer": LOGIN_PAGE})
            if response.status_code >= 400:
                raise LoginError("CareerViet từ chối đăng nhập. Hãy kiểm tra tài khoản hoặc xác minh trên Chrome.")
            self._install_response_cookies(response)
        except requests.RequestException as exc:
            raise LoginError(f"Không kết nối được máy chủ đăng nhập CareerViet: {str(exc)[:100]}")

    def _wait_login(self, minutes=5):
        safe_get(self.driver, LOGIN_PAGE, 1)
        bring_to_front(self.driver)
        self.log("CareerViet cần đăng nhập/xác minh trên Chrome; phần mềm sẽ tự chạy tiếp ngay khi thành công.")
        try:
            initial_auth_cookie = next(
                (c.get("value") for c in self.driver.get_cookies()
                 if c.get("name") == "employer-tokens"), "")
        except Exception:
            initial_auth_cookie = ""
        deadline = time.time() + minutes * 60
        while time.time() < deadline:
            try:
                with self._driver_lock:
                    current_url = self.driver.current_url.lower()
                    current_auth_cookie = next(
                        (c.get("value") for c in self.driver.get_cookies()
                         if c.get("name") == "employer-tokens"), "")
                if ("/login" not in current_url
                        or (current_auth_cookie and current_auth_cookie != initial_auth_cookie)):
                    safe_get(self.driver, CHECK_API, 0.3)
                    if self._read_browser_check_session():
                        return
                    safe_get(self.driver, LOGIN_PAGE, 0.5)
            except Exception:
                pass
            time.sleep(2)
        raise LoginError("Hết thời gian chờ đăng nhập CareerViet. Hãy hoàn tất đăng nhập trên Chrome rồi thử lại.")

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None or getattr(self._local, "token", None) != self._token:
            session = self._cookie_session()
            session.headers["Authorization"] = f"Bearer {self._token}"
            session.headers["x-lang"] = "vi"
            self._local.session = session
            self._local.token = self._token
        return session

    def _refresh(self, rejected_token=""):
        with self._refresh_lock:
            # Another worker may already have refreshed while this request was in flight.
            if rejected_token and self._token and self._token != rejected_token:
                return True
            try:
                response = self._cookie_session().post(
                    REFRESH_API, timeout=30,
                    headers={"Origin": WEB, "Referer": MANAGER_URL})
                cookies_changed = self._install_response_cookies(response)
                body = response.json() if response.status_code == 200 else {}
                token = self._extract_token(body)
                if token:
                    self._token = str(token)
                    self._local = threading.local()
                    return True
                if response.status_code == 200 or cookies_changed:
                    safe_get(self.driver, CHECK_API, 0.3)
                    if (self._read_browser_check_session()
                            and (not rejected_token or self._token != rejected_token)):
                        return True
            except (requests.RequestException, ValueError):
                pass
            if self._read_session() and (not rejected_token or self._token != rejected_token):
                return True
            # Cookies can look valid to /check while the internal API rejects their
            # access token. Perform one credential login instead of recycling it.
            try:
                self._login()
            except LoginError:
                return False
            safe_get(self.driver, CHECK_API, 0.3)
            return (self._read_browser_check_session()
                    and (not rejected_token or self._token != rejected_token))

    def _wait_throttle(self):
        with self._throttle_lock:
            now = time.monotonic()
            ready = self._next_request_at
            interval = self.jitter_delay(
                self._request_interval(), self.request_jitter_ratio)
            self._next_request_at = max(now, ready) + interval
        if ready > now:
            time.sleep(min(ready - now, 60))

    def _request(self, method, url, **kwargs):
        last = None
        timeout = kwargs.pop("timeout", 90)
        for attempt in range(4):
            self._wait_throttle()
            request_token = self._token
            try:
                session = self._session()
                response = session.request(method, url, timeout=timeout, **kwargs)
                _ = getattr(response, "content", None)
                last = response
            except (requests.RequestException, Exception) as exc:
                try:
                    if hasattr(self._local, "session") and self._local.session:
                        self._local.session.close()
                except Exception:
                    pass
                self._local.session = None

                if attempt == 3:
                    raise RuntimeError(f"Lỗi kết nối CareerViet: {str(exc)[:120]}")
                time.sleep(1.0 + 2 ** attempt)
                continue
            if response.status_code == 401:
                if attempt < 3 and self._refresh(request_token):
                    continue
                raise LoginError("Phiên CareerViet đã hết hạn. Hãy đăng nhập lại trên Chrome rồi tiếp tục.")
            if response.status_code in (408, 429, 502, 503, 504) and attempt < 3:
                delay = self._retry_delay(response, attempt)
                self.log(f"CareerViet tạm bận (HTTP {response.status_code}), thử lại sau {delay} giây...")
                with self._throttle_lock:
                    self._next_request_at = max(
                        self._next_request_at, time.monotonic() + delay)
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

    _FETCH_SCRIPT = r"""
        var done = arguments[arguments.length - 1];
        var method = arguments[0], url = arguments[1], token = arguments[2], payload = arguments[3];
        var settled = false;
        function finish(value) { if (!settled) { settled = true; done(value); } }
        var timer = setTimeout(function () { finish({status: 0, error: 'timeout'}); }, 120000);
        var headers = {'Accept': 'application/json, text/plain, */*', 'x-lang': 'vi'};
        if (token) headers.Authorization = 'Bearer ' + token;
        if (payload !== null) headers['Content-Type'] = 'application/json';
        fetch(url, {method: method, headers: headers, credentials: 'include',
                    body: payload === null ? undefined : JSON.stringify(payload)})
          .then(function(response) { return response.arrayBuffer().then(function(buffer) {
              clearTimeout(timer);
              var bytes = new Uint8Array(buffer), binary = '', chunk = 8192;
              for (var i = 0; i < bytes.length; i += chunk)
                  binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
              finish({status: response.status, data_b64: btoa(binary),
                      content_type: response.headers.get('content-type') || '',
                      disposition: response.headers.get('content-disposition') || ''});
          }); }).catch(function(error) { clearTimeout(timer); finish({status: 0, error: String(error)}); });
    """

    def _browser_fetch(self, method, url, payload=None):
        """Fallback through the authenticated browser, serialized across workers."""
        if self.driver is None:
            return None, None, {}
        original_url = ""
        try:
            with self._driver_lock:
                original_url = self.driver.current_url
                # Some CareerViet pages apply a Content-Security-Policy that blocks
                # ad-hoc cross-origin fetch even though their bundled Axios client is
                # allowed. Move temporarily to the API origin so this fallback is a
                # same-origin request, then restore the manager page.
                if not original_url.startswith(INTERNAL):
                    safe_get(self.driver, INTERNAL, 0.2)
                self.driver.set_script_timeout(125)
                result = self.driver.execute_async_script(
                    self._FETCH_SCRIPT, method, url, self._token, payload)
        except Exception:
            return None, None, {}
        finally:
            if original_url and not original_url.startswith(INTERNAL):
                try:
                    with self._driver_lock:
                        safe_get(self.driver, original_url, 0.5)
                except Exception:
                    pass
        if not result or not result.get("data_b64"):
            return (result or {}).get("status"), None, result or {}
        try:
            return result.get("status"), base64.b64decode(result["data_b64"]), result
        except (TypeError, ValueError):
            return result.get("status"), None, result

    @staticmethod
    def _data(body):
        data = body.get("data", body) if isinstance(body, dict) else body
        return data if isinstance(data, (dict, list)) else {}

    def connect(self):
        if self.driver is None:
            self.log("Đang khởi động Chrome cho CareerViet...")
            self.driver = start_driver(self._browser_cfg())
            self.log("Chrome CareerViet đã sẵn sàng. Đang kiểm tra phiên đăng nhập...")

        with self._driver_lock:
            self._cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
            self._ua = self.driver.execute_script("return navigator.userAgent") or self._ua

        session_valid = False
        if self._cookies:
            try:
                res = self._cookie_session().get(CHECK_API, timeout=10)
                if res.status_code == 200:
                    token = self._extract_token(res.json())
                    if token:
                        self._token = str(token)
                        self._local = threading.local()
                        session_valid = True
            except Exception:
                session_valid = False

        if not session_valid:
            if self.cfg.careerviet_email and self.cfg.careerviet_password:
                try:
                    self._login()
                    res = self._cookie_session().get(CHECK_API, timeout=10)
                    if res.status_code == 200:
                        token = self._extract_token(res.json())
                        if token:
                            self._token = str(token)
                            self._local = threading.local()
                            session_valid = True
                except Exception:
                    session_valid = False

        if not session_valid:
            safe_get(self.driver, CHECK_API, 0.3)
            if not self._read_browser_check_session():
                self._wait_login()

        info = self._request("GET", INFO_API)
        if info.status_code != 200:
            raise LoginError(f"Không đọc được tài khoản CareerViet (HTTP {info.status_code}).")
        body = self._data(info.json())
        self._user_id = str(body.get("user_id") or body.get("id") or
                            (body.get("user") or {}).get("id") or "")
        if not self._user_id:
            raise LoginError("CareerViet không trả về mã tài khoản nhà tuyển dụng.")
        page, metadata = self._fetch_page(1)
        self._first_page = page
        self._total = int(metadata.get("itemCount") or metadata.get("total") or len(page))
        self._last_page = int(metadata.get("pageCount") or math.ceil(self._total / PAGE_SIZE))
        self.log(f"CareerViet: tìm thấy {self._total:,} lượt ứng tuyển trên {self._last_page:,} trang.")

    def _fetch_page(self, page):
        params = {"page": int(page), "limit": PAGE_SIZE, "user_id": self._user_id}
        body = None
        response = None
        try:
            response = self._request("GET", LIST_API, params=params)
            if response is not None and response.status_code == 200:
                body = response.json()
        except Exception:
            body = None
        if body is None:
            from urllib.parse import urlencode
            status, raw, _ = self._browser_fetch("GET", f"{LIST_API}?{urlencode(params)}")
            if status == 200 and raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    body = None
            if body is None:
                raise RuntimeError(f"CareerViet trả về HTTP {response.status_code if response else 'Err'} khi đọc trang {page}")
        rows = body.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("data") or []
        return [self._normalize(row) for row in rows], (body.get("metadata") or {})

    @staticmethod
    def _timestamp(value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo:
                parsed = parsed.astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
        for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M"):
            try:
                return datetime.strptime(raw[:19], fmt).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        return raw[:19].replace("T", " ")

    @staticmethod
    def _salary(row):
        low = row.get("resume_targetjob_salary") or row.get("resume_ref_salary")
        high = row.get("resume_targetjob_to_salary") or row.get("resume_ref_to_salary")
        unit = str(row.get("resume_salary_unit") or "").upper()
        values = [str(x) for x in (low, high) if x not in (None, "", 0, "0")]
        return " - ".join(values) + ((" " + unit) if values and unit else "")

    @staticmethod
    def _encode_id(value):
        """CareerViet expects numeric folder/job IDs offset and encoded as hex."""
        raw = str(value or "").strip()
        if not raw:
            return ""
        if any(char in "ABCDEFabcdef" for char in raw):
            return raw.upper()
        try:
            return format(900_000_000 + int(raw), "X")
        except (TypeError, ValueError):
            return raw

    def _normalize(self, row):
        application_id = str(row.get("folder_resume_id") or
                             f"{row.get('job_id', '')}:{row.get('resume_id', '')}")
        applied_ts = self._timestamp(row.get("created_at") or row.get("fresume_create_date1"))
        try:
            applied_at = datetime.strptime(applied_ts, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
        except ValueError:
            applied_at = applied_ts
        job_position = str(row.get("job_title_vn") or row.get("job_title") or
                           row.get("job_name_vn") or row.get("job_name") or
                           row.get("job_apply_title") or row.get("applied_job_title") or
                           row.get("fresume_job_title") or row.get("job_headline") or
                           row.get("folder_name") or row.get("resume_last_job") or
                           row.get("resume_headline_vn") or "").strip()
        return {
            "source": self.key, "account": account_for_source(self.cfg, self.key), "cv_id": application_id,
            "fullname": row.get("jobseeker_fullname") or row.get("job_apply_jobseeker_name") or "",
            "email": row.get("jobseeker_email") or "", "phone": "",
            "position": job_position,
            "campaign_id": str(row.get("job_id") or ""),
            "applied_at": applied_at, "applied_ts": applied_ts,
            "apply_source": "CareerViet", "status": str(row.get("folder_resume_status") or ""),
            "experience": str(row.get("resume_year_of_experience") or ""),
            "years_experience": str(row.get("resume_year_of_experience") or ""),
            "city": row.get("resume_location_vn") or "",
            "current_title": row.get("resume_last_job") or row.get("resume_headline_vn") or "",
            "last_company": row.get("resume_last_company") or "",
            "education": row.get("degree_name_vn") or "",
            "expected_salary": self._salary(row),
            "candidate_id": str(row.get("jobseeker_id") or ""),
            "resume_id": str(row.get("resume_id") or ""),
            "profile_type": str(row.get("resume_kind") or ""),
            "is_viewed": 1 if row.get("folder_resume_viewed") else 0,
            "note": row.get("note_content") or "", "labels": row.get("folder_name") or "",
            "cv_url": MANAGER_URL, "detail_loaded": 0,
            "source_payload": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            "_folder_resume_id": application_id, "_resume_id": str(row.get("resume_id") or ""),
        }

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
                items, metadata = self._first_page, {"pageCount": self._last_page}
            else:
                items, metadata = self._fetch_page(page)
            if not items:
                current_last = int(metadata.get("pageCount") or self._last_page)
                if page <= min(end_page, current_last):
                    raise RuntimeError(f"CareerViet trả về trang {page} rỗng bất thường; giữ checkpoint để thử lại.")
                return
            yield page, items

    def iter_reconciliation(self, depth=2):
        """Re-read newest pages after a long full backup to catch records inserted meanwhile."""
        for page in range(1, min(int(depth), self._last_page) + 1):
            yield self._fetch_page(page)[0]

    @staticmethod
    def _pick(data, *keys):
        if not isinstance(data, dict):
            return ""
        for key in keys:
            value = data.get(key)
            if value not in (None, "", []):
                return value
        for value in data.values():
            if isinstance(value, dict):
                found = CareerVietProvider._pick(value, *keys)
                if found not in (None, "", []):
                    return found
        return ""

    def _load_detail(self, item):
        resume_id = str(item.get("resume_id") or item.get("_resume_id") or "")
        folder_id = str(item.get("cv_id") or item.get("_folder_resume_id") or "")
        if not resume_id:
            raise RuntimeError("Hồ sơ CareerViet thiếu resume_id")
        body = None
        response = None
        try:
            response = self._request("GET", f"{DETAIL_API}/{resume_id}/detail",
                                     params={"folder_resume_id": self._encode_id(folder_id)})
            if response is not None and response.status_code == 200:
                body = response.json()
        except Exception:
            body = None

        if body is None:
            from urllib.parse import urlencode
            query = urlencode({"folder_resume_id": self._encode_id(folder_id)})
            status, raw, _ = self._browser_fetch("GET", f"{DETAIL_API}/{resume_id}/detail?{query}")
            if status == 200 and raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    body = None
            if body is None:
                raise RuntimeError(f"HTTP {response.status_code if response else 'Err'} khi đọc chi tiết CareerViet")
        detail = self._data(body)
        attachment_url = str(self._pick(detail, "resume_attachment_url") or "")
        birthday = self._pick(detail, "jobseeker_birthday", "birthday")
        job_title = self._pick(detail, "job_title_vn", "job_title", "job_name_vn", "job_name",
                               "job_apply_title", "applied_job_title", "fresume_job_title", "job_headline")
        item.update({
            "fullname": self._pick(detail, "jobseeker_fullname") or item.get("fullname", ""),
            "email": self._pick(detail, "jobseeker_email", "email") or item.get("email", ""),
            "phone": self._pick(detail, "jobseeker_mobile", "mobile", "phone") or item.get("phone", ""),
            "position": str(job_title).strip() if job_title else item.get("position", ""),
            "gender": str(self._pick(detail, "gender_name", "jobseeker_gender", "gender")
                          or item.get("gender", "")),
            "birth_year": self._birth_year(birthday) or item.get("birth_year", ""),
            "address": self._pick(detail, "jobseeker_address", "address", "resume_address")
                       or item.get("address", ""),
            "city": self._pick(detail, "jobseeker_location_name_vn") or item.get("city", ""),
            "district": self._pick(detail, "jobseeker_district_name_vn") or item.get("district", ""),
            "current_title": self._pick(detail, "resume_last_job", "resume_headline_vn")
                             or item.get("current_title", ""),
            "job_level": self._pick(detail, "resume_present_level_name_vn", "resume_level_name_vn")
                         or item.get("job_level", ""),
            # Các trường "mong muốn" chỉ có trên trang chi tiết (UI hiển thị:
            # "Địa điểm", "Cấp bậc mong muốn", "Ngành nghề mong muốn", "Ngoại
            # ngữ"). Key JSON đã XÁC NHẬN bằng dump `detail` thật (2026-09-05):
            # `resume_districts` (danh sách tỉnh + quận), `resume_level_name_vn`
            # (đây là cấp bậc MONG MUỐN — `resume_present_level_name_vn` mới là
            # cấp bậc hiện tại), `resume_industries`, `resume_languages`. Xem
            # KINH_NGHIEM_TRIEN_KHAI_CAC_KENH_TUYEN_DUNG.md mục 41.
            "desired_location": self._format_districts(detail.get("resume_districts"))
                                or item.get("desired_location", ""),
            "desired_level": self._pick(detail, "resume_level_name_vn")
                             or item.get("desired_level", ""),
            "desired_position": self._format_named_list(
                detail.get("resume_industries"), "industry_name_vn")
                or item.get("desired_position", ""),
            "foreign_language": self._format_named_list(
                detail.get("resume_languages"), "certification")
                or item.get("foreign_language", ""),
            "marital_status": self._pick(detail, "jobseeker_marital_name_vn", "jobseeker_marital")
                              or item.get("marital_status", ""),
            "education": self._pick(detail, "resume_degree_name_vn") or item.get("education", ""),
            "expected_salary": self._detail_salary(detail) or item.get("expected_salary", ""),
            "skills": self._format_list(self._pick(detail, "resume_skills", "skills")) or item.get("skills", ""),
            "last_company": self._pick(detail, "resume_last_company") or item.get("last_company", ""),
            "experience": str(self._pick(detail, "resume_year_of_experience") or item.get("experience", "")),
            "years_experience": str(self._pick(detail, "resume_year_of_experience")
                                    or item.get("years_experience", "")),
            "labels": self._pick(detail, "folder_name") or item.get("labels", ""),
            "note": self._pick(detail, "folder_resume_note_content") or item.get("note", ""),
            "profile_type": str(self._pick(detail, "resume_kind") or item.get("profile_type", "")),
            "attachment_name": self._attachment_name(attachment_url) or item.get("attachment_name", ""),
            "attachment_mime": "application/pdf" if attachment_url.lower().endswith(".pdf")
                               else item.get("attachment_mime", ""),
            "_attachment_url": attachment_url,
            "detail_loaded": 1,
            "source_payload": json.dumps({"list": self._payload(item), "detail": detail},
                                         ensure_ascii=False, separators=(",", ":")),
        })
        return item

    @staticmethod
    def _payload(item):
        try:
            raw = json.loads(item.get("source_payload") or "{}")
            return raw.get("list", raw) if isinstance(raw, dict) else raw
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _format_list(value):
        if isinstance(value, list):
            return ", ".join(str(x.get("name") or x.get("skill_name") or x)
                             if isinstance(x, dict) else str(x) for x in value)
        return str(value or "")

    @staticmethod
    def _format_named_list(value, key):
        """Ghép các phần tử `{key: '...'}` của một list JSON thành chuỗi."""
        if not isinstance(value, list):
            return ""
        parts = [str(x.get(key)).strip() for x in value
                 if isinstance(x, dict) and x.get(key)]
        return ", ".join(dict.fromkeys(p for p in parts if p))

    @staticmethod
    def _format_districts(value):
        """`resume_districts` (địa điểm làm việc mong muốn) có dạng
        `[{location_name, districts:[{district_name_vn}]}]` — ghép thành
        "Tỉnh (quận, quận...)" như UI CareerViet hiển thị."""
        if not isinstance(value, list):
            return ""
        from ..geo import canonical_province
        out = []
        for group in value:
            if not isinstance(group, dict):
                continue
            province = str(group.get("location_name") or "").strip()
            if not province:
                continue
            province = canonical_province(province) or province
            districts = [str(d.get("district_name_vn")).strip()
                         for d in (group.get("districts") or [])
                         if isinstance(d, dict) and d.get("district_name_vn")]
            out.append(f"{province} ({', '.join(districts)})" if districts else province)
        return "; ".join(out)

    @classmethod
    def _detail_salary(cls, detail):
        row = {
            "resume_targetjob_salary": cls._pick(detail, "resume_target_job_salary"),
            "resume_targetjob_to_salary": cls._pick(detail, "resume_target_job_to_salary"),
            "resume_ref_salary": cls._pick(detail, "resume_ref_salary"),
            "resume_ref_to_salary": cls._pick(detail, "resume_ref_to_salary"),
            "resume_salary_unit": cls._pick(detail, "resume_salary_unit"),
        }
        return cls._salary(row)

    @staticmethod
    def _birth_year(value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return str(datetime.strptime(raw[:10], fmt).year)
            except ValueError:
                continue
        return raw[:4] if raw[:4].isdigit() else ""

    @staticmethod
    def _attachment_name(url):
        try:
            return urlparse(str(url or "")).path.rsplit("/", 1)[-1]
        except Exception:
            return ""

    def enrich(self, item):
        return self._load_detail(item)

    def refresh_failed_item(self, item):
        """Làm mới đúng resume/folder id qua API chi tiết, không quét danh sách."""
        self._load_detail(item)
        return True

    def download(self, item_or_id):
        item = item_or_id if isinstance(item_or_id, dict) else {"cv_id": str(item_or_id)}
        try:
            if not item.get("detail_loaded"):
                try:
                    self._load_detail(item)
                except Exception as exc:
                    self.log(f"  ! Chưa đọc được chi tiết CareerViet, vẫn thử tải CV: {str(exc)[:100]}")
            resume_id = str(item.get("resume_id") or item.get("_resume_id") or "")
            data = None
            ext = None
            response = None
            try:
                response = self._request("POST", f"{DETAIL_API}/{resume_id}/export-pdf",
                                         timeout=120)
                if response is not None and 200 <= response.status_code < 300:
                    data = response.content
                    ext = (sniff_ext(data) or response_ext(response)) if data else None
            except Exception as req_exc:
                self.log(f"  ! Tải trực tiếp CareerViet gặp lỗi ({str(req_exc)[:80]}), đang chuyển sang tải qua trình duyệt...")

            if not data or not ext:
                status, browser_data, _ = self._browser_fetch(
                    "POST", f"{DETAIL_API}/{resume_id}/export-pdf")
                if status and 200 <= status < 300 and browser_data:
                    data = browser_data
                    ext = sniff_ext(data)

            if not data or not ext:
                if response is not None and not (200 <= response.status_code < 300):
                    return None, f"CareerViet trả về HTTP {response.status_code} khi tải CV"
                return None, "Nội dung CareerViet trả về không phải file CV hợp lệ hoặc kết nối bị ngắt"
            return data, ext
        except LoginError:
            raise
        except Exception as exc:
            return None, str(exc)[:180]

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
