# -*- coding: utf-8 -*-
"""
Smoke test tối thiểu cho MSB Radar Edge - CHẠY TRƯỚC KHI đóng gói .exe / phát hành bản mới.

Không cần cài thêm gì ngoài Python chuẩn (không phụ thuộc pytest hay bất kỳ thư viện nào
trong requirements.txt) - chủ đích để không có lý do gì bỏ qua bước này trước khi đóng gói.

Kiểm tra đúng các LOẠI lỗi đã từng xảy ra thật trên dự án này:
  1. Toàn bộ file .py trong app/ biên dịch được (bắt lỗi cú pháp trước khi đóng gói .exe -
     kiểu lỗi từng làm crash app ngay lúc khởi động: "NameError: name 'PRIMARY' is not defined").
  2. app.js không có lỗi cú pháp (nếu máy có sẵn Node.js - bỏ qua nếu không có).
  3. Mọi document.getElementById('...') trong app.js đều có phần tử id="..." tương ứng
     trong index.html, HOẶC do chính app.js tự tạo ra lúc chạy (id="..." bên trong chuỗi
     template render biểu đồ/bảng). Đây đúng là loại lỗi đã gây ra "Dữ liệu ứng viên tải
     mãi không xong" (thiếu hẳn #filter-position trong HTML khiến loadCandidates() ném lỗi
     giữa chừng, để lại dòng "Đang tải dữ liệu..." treo vĩnh viễn).
  4. Mọi lệnh gọi this.api.xxx(...) trong app.js đều khớp với 1 hàm thật trong lớp Api
     (app/web_api.py) - tránh gọi nhầm tên hàm không tồn tại (JS gọi Python qua pywebview
     không có type-check, gõ sai tên hàm chỉ lộ ra khi bấm nút, dễ lọt qua mắt).
  5. Các hàm truy vấn trong app/db.py (query, stats, stats_by_position, stats_by_day,
     distinct) chạy được trên 1 cơ sở dữ liệu SQLite rỗng, tạo TẠM trong thư mục temp -
     KHÔNG đụng tới dữ liệu hay file cauhinh.json thật của người dùng.

Cách chạy:
    python tests/smoke_test.py

Thoát mã 0 nếu mọi thứ ổn, khác 0 kèm danh sách lỗi cụ thể nếu có vấn đề - dùng được luôn
trong build_exe.py hoặc 1 bước CI để chặn đóng gói khi còn lỗi.
"""
import os
import re
import subprocess
import sys
import tempfile

# Không ghi file .pyc ra __pycache__ khi import app.db ở bước [5/5] - dự án thường nằm
# trong thư mục Google Drive đồng bộ, mà ổ ảo của Drive đôi khi khoá đúng lúc Python
# đang ghi bytecode, gây lỗi PermissionError chớp nhoáng không liên quan gì tới chất
# lượng code (đã xảy ra thật, làm cả lượt đóng gói dừng vì lý do ngoài code).
sys.dont_write_bytecode = True

# Console Windows mac dinh chay codepage cp1252/cp1258 (khong phai UTF-8), nen bat ky
# chuoi tieng Viet co dau nao lot vao print() (vd tu 1 exception message) se lam chinh
# smoke test nay crash truoc khi kip bao loi that. Ep stdout/stderr sang UTF-8 tu dau.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../edge
APP_DIR = os.path.join(ROOT, "app")
WEB_DIR = os.path.join(APP_DIR, "web")

_errors = []


def _fail(msg):
    # Dung ky hieu ASCII thuan, khong dung Unicode (vd ✓/✗) - console Windows mac dinh
    # chay codepage cp1252/cp1258, in ky tu ngoai bang do se crash UnicodeEncodeError
    # ngay trong luc chay smoke test - chinh no la 1 dang loi ma test nay ton tai de chan.
    _errors.append(msg)
    print(f"  [FAIL] {msg}")


def _ok(msg):
    print(f"  [OK] {msg}")


def _warn(msg):
    print(f"  [WARN] {msg}")


def check_python_syntax():
    print("[1/6] Bien dich toan bo file .py trong app/ ...")
    py_files = []
    for dirpath, _dirs, files in os.walk(APP_DIR):
        if "__pycache__" in dirpath:
            continue
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(dirpath, f))
    if not py_files:
        _fail("Khong tim thay file .py nao trong app/ - duong dan sai?")
        return

    # Bien dich TRONG BO NHO (compile(), khong ghi file .pyc ra dia) - chi can kiem tra
    # cu phap, khong can luu bytecode. "python -m py_compile" ghi .pyc vao __pycache__
    # canh tung file nguon; khi thu muc du an nam tren Google Drive, o ao cua Drive doi
    # khi khoa dung luc dang ghi -> loi PermissionError chop nhoang khong lien quan gi
    # den chat luong code, chi vi tac dung phu khong can thiet nay.
    loi = []
    for path in py_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
            compile(source, path, "exec")
        except SyntaxError as e:
            loi.append(f"{path}: {e}")
        except OSError as e:
            loi.append(f"{path}: khong doc duoc file ({e})")
    if loi:
        _fail("Loi cu phap Python:\n" + "\n".join(loi))
    else:
        _ok(f"{len(py_files)} file .py OK")


def check_js_syntax():
    print("[2/6] Kiem tra cu phap app.js (Node.js) ...")
    app_js = os.path.join(WEB_DIR, "app.js")
    try:
        r = subprocess.run(["node", "--check", app_js], capture_output=True, text=True)
    except FileNotFoundError:
        _warn("Khong tim thay Node.js tren may - bo qua buoc nay.")
        return
    if r.returncode != 0:
        _fail(f"Loi cu phap app.js:\n{r.stderr}")
    else:
        _ok("app.js OK")


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def check_dom_ids():
    print("[3/6] Doi chieu document.getElementById(...) trong app.js voi index.html ...")
    js = _read(WEB_DIR, "app.js")
    html = _read(WEB_DIR, "index.html")

    used_ids = set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", js))
    html_ids = set(re.findall(r'id=["\']([^"\']+)["\']', html))
    # id="..." ma chinh app.js tu tao ra luc chay (trong chuoi template render bieu do...)
    js_dynamic_ids = set(re.findall(r'id=["\']([^"\']+)["\']', js))

    missing = used_ids - html_ids - js_dynamic_ids
    if missing:
        _fail(f"getElementById dung id KHONG ton tai o dau ca: {sorted(missing)}")
    else:
        _ok(f"{len(used_ids)} id deu ton tai (tinh trong HTML hoac do JS tu tao)")


def check_api_methods():
    print("[4/6] Doi chieu this.api.xxx(...) trong app.js voi lop Api (web_api.py) ...")
    js = _read(WEB_DIR, "app.js")
    py = _read(APP_DIR, "web_api.py")

    used_calls = set(re.findall(r"this\.api\.([a-zA-Z_][a-zA-Z0-9_]*)", js))
    defined_methods = set(re.findall(r"^\s{4}def ([a-zA-Z_][a-zA-Z0-9_]*)", py, re.MULTILINE))

    missing = used_calls - defined_methods
    if missing:
        _fail(f"app.js goi this.api.xxx() khong co trong class Api: {sorted(missing)}")
    else:
        _ok(f"{len(used_calls)} lenh goi API deu khop ham that")


def check_db_layer():
    print("[5/6] Chay thu cac ham truy van app/db.py tren CSDL tam, rong ...")
    sys.path.insert(0, ROOT)
    try:
        from app.db import Database
    except Exception as e:
        _fail(f"Khong import duoc app.db: {e}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "smoke_test.db")
        db = Database(db_path).open()
        try:
            db.upsert({
                "source": "topcv", "cv_id": "1", "fullname": "Nguyen Van Test",
                "position": "Nhan vien kiem thu", "dl_status": "Đã tải",
                "applied_ts": "2026-01-01 08:00:00",
            })
            db.commit()

            rows, total = db.query(limit=10, offset=0)
            assert total == 1 and len(rows) == 1, "query() tra ve sai so dong"
            light_rows, _ = db.query(limit=10, columns=("source", "cv_id", "fullname"))
            assert set(light_rows[0].keys()) == {"source", "cv_id", "fullname"}, \
                "Query danh sach van doc cac cot payload nang khong can hien thi"

            st = db.stats()
            assert st["total"] == 1, "stats() sai tong so"

            by_pos = db.stats_by_position()
            assert by_pos and by_pos[0]["position"] == "Nhan vien kiem thu", \
                "stats_by_position() sai du lieu"

            by_day = db.stats_by_day(days=30)
            assert isinstance(by_day, list), "stats_by_day() phai tra ve list"

            db.distinct("position")

            columns = {r[1] for r in db.conn.execute("PRAGMA table_info(candidates)")}
            required = {"education", "skills", "current_title", "expected_salary", "source_payload",
                        "candidate_id", "resume_id", "detail_loaded"}
            assert required <= columns, "Database thieu cac cot chi tiet ung vien moi"

            # Upsert danh sach khong duoc xoa du lieu chi tiet da lay truoc do.
            db.upsert({"source": "topcv", "cv_id": "1", "fullname": "Nguyen Van Test",
                       "education": "Dai hoc", "detail_loaded": 1})
            db.upsert({"source": "topcv", "cv_id": "1", "fullname": "Nguyen Van Test"})
            db.commit()
            preserved = db.get_candidate("topcv", "1")
            assert preserved["education"] == "Dai hoc", "Upsert da lam mat du lieu chi tiet"

            from app.engine import SyncEngine
            from types import SimpleNamespace
            cv_dir = os.path.join(tmp, "cv")
            os.makedirs(cv_dir)
            cfg = SimpleNamespace(filename_pattern="{id}_{ten}", cv_folder=cv_dir,
                                  skip_existing_file=True, delay_ms=0)
            engine = SyncEngine(cfg, source="topcv")
            provider = type("P", (), {"download": lambda self, item: (b"%PDF-1.7\ntest", ".pdf")})()
            engine._process_one(provider, db, {
                "source": "topcv", "cv_id": "atomic-1", "fullname": "Atomic Test"
            }, set(), db.all_ids("topcv"))
            assert any(x.endswith(".pdf") for x in os.listdir(cv_dir)), "Khong ghi duoc file CV"
            assert not any(x.endswith(".part") for x in os.listdir(cv_dir)), \
                "Con file .part sau khi ghi CV thanh cong"

            today = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for cv_id, position, channel in (("vw-1", "Ke toan", "VietnamWorks"),
                                              ("vw-2", "Ke toan", "VietnamWorks"),
                                              ("vw-3", "Nhan su", "Referral")):
                db.upsert({"source": "vietnamworks", "cv_id": cv_id, "fullname": cv_id,
                           "position": position, "apply_source": channel,
                           "applied_ts": today, "dl_status": "Đã tải"})
            db.commit()
            report_stats = db.stats(source="vietnamworks", position="Ke toan")
            assert report_stats["total"] == 2 and report_stats["done"] == 2, \
                "KPI bao cao khong loc dung vi tri"
            assert db.stats_by_position(source="vietnamworks", position="Ke toan")[0]["count"] == 2, \
                "Bieu do vi tri khong loc dung vi tri"
            assert sum(x["count"] for x in db.stats_by_day(
                source="vietnamworks", position="Ke toan")) == 2, \
                "Bieu do xu huong khong loc dung vi tri"
            assert db.stats(source="vietnamworks", apply_source="VietnamWorks")["total"] == 2, \
                "KPI bao cao khong loc dung kenh"
            assert db.stats_by_channel(source="vietnamworks")[0]["count"] == 2, \
                "Bao cao theo kenh khong chinh xac"
            assert db.stats_by_source()[0]["count"] >= 3, \
                "Bao cao theo nguon khong chinh xac"
            assert db.stats_by_status(source="vietnamworks")[0]["count"] == 3, \
                "Bao cao trang thai tuyen dung khong chinh xac"
            quality = db.stats_quality(source="vietnamworks")
            assert quality["n"] == 3, "Bao cao chat luong du lieu khong chinh xac"
            from app.web_api import Api
            api = Api()
            api._cfg.db_path = db_path
            captured_query = {}
            class FakeListDb:
                def query(self, **kwargs):
                    captured_query.update(kwargs)
                    return [], 0
                def candidate_alerts(self, rows):
                    return {}
                def candidate_filter_breakdown(self, **kwargs):
                    return {"by_source": [], "by_year": []}
                def get_document_summaries(self, identities):
                    return {}
            real_db_method = api._db
            api._db = lambda: FakeListDb()
            candidate_page = api.get_candidates({"limit": 1000000, "offset": -20})
            assert captured_query["limit"] == 200 and captured_query["offset"] == 0, \
                "API du lieu ung vien chua chan yeu cau full data"
            assert "source_payload" not in captured_query["columns"] and "positions" not in candidate_page, \
                "API danh sach van doc payload nang hoac query DISTINCT thua"
            api._db = real_db_method
            report = api.get_report({"source": "vietnamworks", "position": "Ke toan"})
            assert report["total"] == 2 and report["done"] == 2, \
                "API bao cao khong loc dung vi tri"
            assert report["by_source"] and report["by_status"] == [] and "quality_rates" in report, \
                "API bao cao thieu quan ly nguon/chat luong hoac van tinh bieu do trang thai da bo"
            assert "average_per_period" in report and "peak" in report and "change_percent" in report, \
                "API bao cao thieu chi so quan tri theo thoi gian"
            assert set(report["positions"]) == {"Ke toan", "Nhan su"}, \
                "API khong tra du danh sach vi tri theo nguon"
            channel_report = api.get_report({
                "source": "vietnamworks", "channel": "VietnamWorks", "time_range": "all"})
            assert channel_report["total"] == 2 and channel_report["granularity"] == "month", \
                "API bao cao khong ket hop dung kenh va thoi gian"
            all_report = api.get_report({"source": "", "time_range": "all"})
            assert all_report["total"] == db.count(), "Tuy chon tat ca nguon khong chinh xac"
            assert all_report["channels"] == [], \
                "Loai ho so bi tron giua TopCV va VietnamWorks khi xem tat ca kenh"
            today_key = today[:10]
            today_report = api.get_report({"source": "vietnamworks", "time_range": "today"})
            assert today_report["total"] == 3 and len(today_report["by_day"]) == 1, \
                "Bo loc bao cao hom nay khong chinh xac"
            custom_report = api.get_report({
                "source": "vietnamworks", "time_range": "custom",
                "date_from": today_key, "date_to": today_key})
            assert custom_report["total"] == 3, "Khoang ngay tuy chon khong chinh xac"
            db.upsert({"source": "topcv", "cv_id": "bad-date", "fullname": "Bad Date",
                       "applied_ts": "1741340-01", "dl_status": "Đã tải"})
            db.commit()
            # Mô phỏng tín hiệu vô hiệu hóa cache mà luồng tải thật gửi sau khi ghi.
            api._report_cache.clear()
            api._report_cache_at.clear()
            invalid_date_report = api.get_report({"source": "", "time_range": "all"})
            assert invalid_date_report["invalid_date_rows"] == 1, \
                "Bao cao khong bo qua va canh bao ngay ung tuyen sai dinh dang"
            app_js = open(os.path.join(ROOT, "app", "web", "app.js"), encoding="utf-8").read()
            assert "sourceFilter.value = res.source" not in app_js, \
                "Tai xong mot kenh van tu dong loc bang ung vien theo kenh do"
            assert "`${st.total.toLocaleString()} hồ sơ`" in app_js, \
                "Sidebar chua hien tong ho so cua toan bo database"
            api._close_db()

            _ok("query / stats / stats_by_position / stats_by_day / distinct deu chay OK")
        except Exception as e:
            import traceback
            traceback.print_exc()
            _fail(f"Loi khi chay thu app/db.py: {e}")
        finally:
            db.close()


def check_vietnamworks_provider():
    print("[6/6] Kiem tra contract provider VietnamWorks ...")
    sys.path.insert(0, ROOT)
    try:
        from app.providers import PROVIDERS_BY_KEY
        from app.providers.vietnamworks import (
            VietnamWorksProvider, PAGE_SIZE, DETAIL_QUERY, GRAPHQL, JOB_LIST_QUERY,
            JOB_INDEX_URL)
        from app.browser import _start_with_watchdog
        from app.config import AppConfig
        import inspect
        import json
        import threading

        cls = PROVIDERS_BY_KEY.get("vietnamworks")
        assert cls is VietnamWorksProvider and cls.available, "VietnamWorks chua duoc dang ky/bat"
        assert cls.max_concurrency == 4, "VietnamWorks chua gioi han concurrency an toan"
        limits = cls.__new__(cls)
        limits.run_mode = "tatca"
        assert limits.concurrency_limit() == 2, \
            "Backup lich su VietnamWorks chua tu ha so luong luong tai"
        assert limits.minimum_item_delay_ms() >= 600 and limits._request_interval() >= 0.25, \
            "Backup lich su VietnamWorks chua co nhip tai an toan"
        limits.run_mode = "moi"
        assert limits.concurrency_limit() == cls.max_concurrency, \
            "Che do CV moi bi gioi han cham nhu backup lich su"
        assert AppConfig().schedule_source == "topcv", "Thieu cau hinh nguon hen gio"
        web_api_source = open(os.path.join(ROOT, "app", "web_api.py"), encoding="utf-8").read()
        assert 'for source in job.get("sources", [])' in web_api_source and \
               "self.start_download(source, job.get(\"mode\", \"moi\")" in web_api_source, \
            "Hen gio chua lap qua danh sach nhieu nguon"
        assert PAGE_SIZE == 20, "Sai kich thuoc trang ung vien VietnamWorks"
        assert cls.safe_first_page_no_change is False, \
            "Khong duoc bo quet chi vi trang dau cua mot job khong doi"
        assert all(x in DETAIL_QUERY for x in ("cellphone", "attachmentPath", "canDownload")), \
            "Query chi tiet thieu du lieu lien he/file CV"
        assert all(x in JOB_LIST_QUERY for x in ("jobList", "totalApplication", "numOfApplications")), \
            "Query danh muc job cu thieu tong ho so"
        assert JOB_INDEX_URL.endswith("/v2/job/default/index"), \
            "Chrome VietnamWorks chua mo trang quan ly job day du"
        marker = object()
        assert _start_with_watchdog(lambda: marker, "unused", timeout=0.1) is marker, \
            "Watchdog khoi dong Chrome lam sai ket qua thanh cong"
        params = list(inspect.signature(cls.iter_pages).parameters)
        assert params == ["self", "start_page", "end_page", "reverse"], \
            "iter_pages khong khop contract engine"
        provider = cls.__new__(cls)
        provider.cfg = AppConfig(vietnamworks_email="test@example.com")
        provider._last_page = 3
        provider._tasks = [
            ({"totalApplication": 25}, 1),
            ({"totalApplication": 7}, 1),
            ({"totalApplication": 25}, 2),
        ]
        assert provider.range_total(1, 3) == 32 and provider.range_total(3, 3) == 5, \
            "Tinh tong ung vien theo trang ao khong chinh xac"
        provider._graphql = lambda *args, **kwargs: {"detailApplicationAction": {"resumeData": {
            "userInfo": {"emailAddress": "test@example.com", "cellphone": "0900000000",
                         "address": "Ha Noi", "district": "Cau Giay", "cityName": "Ha Noi"},
            "userInfoDegreeData": [{"degreeName": "Dai hoc"}],
            "applicationInfo": {"fullName": "Ung Vien Test", "attachmentFileAlias": "cv.pdf",
                                "attachmentFileMime": "application/pdf", "appTypeSource": "Attached"},
            "searchableResume": {"mostRecentJobTitle": "Chuyen vien", "currentJobLevel": "Senior"},
            "resume": {"skills": [{"name": "Python"}], "mostRecentCompany": "Cong ty A"},
        }}}
        item = {"cv_id": "123", "source": "vietnamworks"}
        provider._load_detail(item)
        assert all(item.get(k) for k in ("email", "phone", "district", "education", "skills",
                                         "current_title", "job_level", "attachment_name",
                                         "attachment_mime", "source_payload", "detail_loaded")), \
            "Chua anh xa du thong tin chi tiet VietnamWorks"

        list_item = provider._normalize({
            "applicationId": 9, "jobAppType": 3, "candidateId": 4, "resumeId": 5,
        }, {"id": 7, "title": "Test"})
        assert list_item["_app_type"] == 3, "appType dang bi hard-code"
        assert cls._trusted_auth_url(GRAPHQL), "GraphQL phai duoc gui Bearer"
        assert not cls._trusted_auth_url("https://cdn.example.com/cv.pdf"), \
            "Khong duoc gui Bearer VietnamWorks sang CDN khac domain"

        class FakeResponse:
            def __init__(self, status, body=None, headers=None, content=b""):
                self.status_code = status
                self._body = body or {}
                self.headers = headers or {}
                self.content = content
            def json(self):
                return self._body

        assert cls._retry_delay(FakeResponse(429, headers={"Retry-After": "7"}), 0) == 7, \
            "Chua ton trong Retry-After cua VietnamWorks"

        fallback = cls.__new__(cls)
        fallback._request = lambda *a, **k: FakeResponse(403)
        fallback._browser_fetch = lambda *a, **k: (
            200, json.dumps({"data": {"ok": True}}).encode("utf-8"))
        assert fallback._graphql("query { ok }", {}) == {"ok": True}, \
            "GraphQL khong fallback qua Chrome khi HTTP truc tiep loi"

        retry = cls.__new__(cls)
        retry._token = "old"
        retry._throttle_lock = threading.Lock()
        retry._throttle_until = 0.0
        retry._wait_throttle = lambda: None
        calls = []
        responses = iter([FakeResponse(401), FakeResponse(200)])
        retry._session = lambda: type("S", (), {"request": lambda self, *a, **k:
            (calls.append(k.get("headers", {})) or next(responses))})()
        retry._refresh_session = lambda rejected: setattr(retry, "_token", "new")
        assert retry._request("GET", "https://employer.vietnamworks.com/api/my-job").status_code == 200
        assert calls[0].get("Authorization") == "Bearer old" and calls[1].get("Authorization") == "Bearer new", \
            "401 khong lam moi Bearer va thu lai"

        discovery = cls.__new__(cls)
        discovery.run_mode = "tatca"
        discovery.log = lambda message: None
        discovery._load_catalog = lambda: {"jobs": {}, "expired_complete": False}
        saved_catalog = {}
        discovery._save_catalog = lambda value: saved_catalog.update(value)
        online = [{"jobId": 10, "jobTitle": "Online", "createdOn": "2026-08-01",
                   "extraInfo": {"totalApplication": 2}}]
        expired = [{"jobId": 11, "jobTitle": "Expired", "createdOn": "2020-01-01",
                    "extraInfo": {"totalApplication": 3}},
                   {"jobId": 12, "jobTitle": "Old zero", "createdOn": "2012-01-01",
                    "extraInfo": {"totalApplication": 0}}]
        discovery._scan_job_type = lambda status, *args, **kwargs: (
            (expired if status == "expired" else online if status in ("online", "expiry7day") else []),
            (2 if status == "expired" else 1 if status in ("online", "expiry7day") else 0), True)
        jobs = discovery._discover_jobs([])
        assert {x["id"] for x in jobs} == {"10", "11"}, \
            "Hop nhat job khong dung hoac chua bo job cu 0/0"
        assert sum(x["totalApplication"] for x in jobs) == 5, \
            "Tong ho so tu danh muc job cu khong chinh xac"
        assert saved_catalog.get("expired_complete") is True, \
            "Khong luu trang thai quet het tab expired"

        invalid_job = cls.__new__(cls)
        invalid_job._invalid_job_ids = set()
        invalid_job.log = lambda message: None
        invalid_calls = []
        def invalid_graphql(*args, **kwargs):
            invalid_calls.append(1)
            raise RuntimeError("VietnamWorks GraphQL: Invalid job")
        invalid_job._graphql = invalid_graphql
        invalid_task = ({"id": "999", "title": "Job da xoa"}, 1)
        assert invalid_job._fetch_task(invalid_task) == [] and invalid_job._fetch_task(invalid_task) == [], \
            "Job lich su da xoa lam dung toan bo luot backup"
        assert len(invalid_calls) == 1 and "999" in invalid_job._invalid_job_ids, \
            "Job invalid chua duoc ghi nho de tranh goi lai"

        incremental = cls.__new__(cls)
        incremental.run_mode = "moi"
        incremental.log = lambda message: None
        incremental._load_catalog = lambda: {"jobs": {"11": jobs[1]}, "expired_complete": True}
        incremental._save_catalog = lambda value: saved_catalog.update(value)
        incremental._scan_job_type = discovery._scan_job_type
        incremental._discover_jobs([])
        assert saved_catalog.get("expired_complete") is True, \
            "Quet CV moi lam mat trang thai catalog lich su da hoan tat"

        capped = cls.__new__(cls)
        capped.log = lambda message: None
        requested_pages = []
        def fake_job_page(status, page, time_filter=0):
            requested_pages.append(page)
            return {"total": 200, "data": [
                {"jobId": page * 100 + index, "extraInfo": {"totalApplication": 1}}
                for index in range(20)]}
        capped._job_list_page = fake_job_page
        _, _, completed = capped._scan_job_type(
            "expired", 5, known={}, full=False, max_pages=5)
        assert requested_pages == [1, 2, 3, 4, 5] and completed is False, \
            "CV moi chua gioi han tham do lich su khi catalog chua hoan tat"

        file_fallback = cls.__new__(cls)
        file_fallback._load_detail = lambda item: {
            "canDownload": True, "attachmentPath": "https://cdn.example.com/cv.pdf", "fileName": "cv.pdf"}
        file_fallback._request = lambda *a, **k: FakeResponse(
            200, headers={"Content-Type": "application/pdf"}, content=b"<html>blocked</html>")
        file_fallback._browser_fetch = lambda *a, **k: (200, b"%PDF-1.7\nvalid")
        file_data, file_ext = file_fallback.download({"cv_id": "1"})
        assert file_data.startswith(b"%PDF") and file_ext == ".pdf", \
            "Noi dung HTML gia PDF khong duoc fallback qua Chrome"
        _ok("VietnamWorks da dang ky; phan trang, quet moi va query chi tiet dung contract")
    except Exception as e:
        _fail(f"Provider VietnamWorks khong dung contract: {e}")


def check_vieclam24h_provider():
    print("[7/7] Kiem tra contract provider Vieclam24h ...")
    sys.path.insert(0, ROOT)
    try:
        from app.providers import PROVIDERS_BY_KEY
        from app.providers.vieclam24h import Vieclam24hProvider, PAGE_SIZE
        from app.config import AppConfig

        cls = PROVIDERS_BY_KEY.get("vieclam24h")
        assert cls is Vieclam24hProvider and cls.available, "Vieclam24h chua duoc dang ky/bat"
        assert cls.max_concurrency == 4, "Vieclam24h chua gioi han concurrency an toan"
        assert PAGE_SIZE == 20, "Sai kich thuoc trang ung vien Vieclam24h"

        provider = cls.__new__(cls)
        provider.cfg = AppConfig(vieclam24h_email="test@example.com")
        provider.key = "vieclam24h"
        norm = provider._normalize({
            "id": 123,
            "seeker_info": {"name": "Test Candidate", "email": "test@gmail.com", "mobile": "0987654321", "gender": 2, "birthday": 946684800},
            "job_info": {"title": "Lập trình viên"},
            "resume_info": {"title": "Developer", "experience": 3},
            "applied_at": 1700000000,
            "file": "/cv/sample.pdf",
            "recruitment_status": 1
        })
        assert norm["source"] == "vieclam24h" and norm["cv_id"] == "123", "Norm cv_id hoac source sai"
        assert norm["fullname"] == "Test Candidate" and norm["email"] == "test@gmail.com", "Norm ho ten/email sai"
        assert norm["gender"] == "Nam" and norm["birth_year"] == "2000", "Norm gioi tinh/nam sinh sai"
        assert norm["cv_url"] == "https://cdn1.vieclam24h.vn/cv/sample.pdf", "Norm cv_url sai"
        _ok("Vieclam24h da dang ky va tuong thích voi contract")
    except Exception as e:
        _fail(f"Provider Vieclam24h khong dung contract: {e}")


def main():
    print("=" * 60)
    print("MSB RADAR EDGE - SMOKE TEST")
    print("=" * 60)
    check_python_syntax()
    check_js_syntax()
    check_dom_ids()
    check_api_methods()
    check_db_layer()
    check_vietnamworks_provider()
    check_vieclam24h_provider()
    print("=" * 60)
    if _errors:
        print(f"KET QUA: THAT BAI - {len(_errors)} loi. KHONG dong goi / phat hanh khi con loi o tren.")
        sys.exit(1)
    print("KET QUA: OK - co the dong goi / phat hanh.")
    sys.exit(0)


if __name__ == "__main__":
    main()
