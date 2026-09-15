# -*- coding: utf-8 -*-
"""
Cầu nối API giữa giao diện Web (Javascript via pywebview) và Python Backend.
"""
import os
import sys
import json
import sqlite3
import threading
import time
import tkinter as tk
import shutil
from functools import wraps
from tkinter import filedialog
from dataclasses import asdict
from datetime import datetime, timedelta

from .config import AppConfig, LOG_PATH, app_dir, rotate_log_if_needed, account_for_source, normalize_account
from .db import Database, DONE, EXPORT_COLUMNS, is_cloud_synced_path
from .sync import SyncService
from .engine import SyncEngine
from .providers import ALL_PROVIDERS
from .exporter import export_rows, export_zip_with_cv
from .notifier import notify
from .about import INTRO, GUIDE, NOTE
from .browser import (ChromeStartError, close_profile_browser, open_profile_browser,
                      profile_browser_processes)
from . import lockfile
from .cv_parser import CvParsingService
from .coordinator import PipelineCoordinator
from . import net
from .prerequisites import runtime_readiness
from .version import APP_DISPLAY_NAME, APP_VERSION


#: Một lượt tải theo lịch bị coi là "treo" nếu chạy quá thời gian này mà chưa
#: xong. Không phải timeout tải trang thông thường (cái đó đã có
#: `set_page_load_timeout` riêng trong browser.py) - đây là lưới an toàn cuối
#: cùng cho trường hợp chromedriver/Chrome bị deadlock ở tầng driver, khiến
#: lệnh Selenium không bao giờ tự trả lời. Đủ rộng cho "Tải tất cả" trên tài
#: khoản lớn (xem KINH_NGHIEM_TRIEN_KHAI_CAC_KENH_TUYEN_DUNG.md mục 40).
SCHEDULED_JOB_MAX_MINUTES = 180

#: Sau khi ép đóng Chrome để gỡ một lượt treo, chờ thêm chừng này để luồng tải
#: tự thoát (lỗi kết nối) trước khi coi là không thể phục hồi an toàn.
SCHEDULED_JOB_KILL_GRACE_SECONDS = 90

#: Một lịch lỗi liên tiếp (vd sai mật khẩu, tài khoản bị khoá) sẽ giãn thêm
#: thời gian nghỉ thay vì cứ đúng `interval_min` lại thử lại vô ích - tối đa
#: 6 tiếng, giống cơ chế ngắt mạch đã có ở đồng bộ Hub (`sync/service.py`).
SCHEDULE_MAX_BACKOFF_MINUTES = 360


def serialized_db_api(method):
    """Giữ nguyên quyền sở hữu connection trong suốt một API nhiều câu SQL."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        lock = getattr(self, "_db_access_lock", None)
        if lock is None:  # Hỗ trợ các unit test tạo Api bằng __new__.
            lock = self._db_access_lock = threading.RLock()
        with lock:
            return method(self, *args, **kwargs)
    return wrapped


def get_about_markdown():
    return f"# Giới Thiệu MSB Radar Edge\n\n{INTRO}\n\n# Hướng Dẫn Sử Dụng\n\n{GUIDE}\n\n*Lưu ý: {NOTE}*"


def notify_new_cvs(count, source="topcv"):
    title = f"MSB Radar Edge — Tìm thấy {count:,} CV mới!"
    msg = f"Đã tự động tải {count:,} hồ sơ ứng viên mới từ nguồn {source.upper()}."
    notify(title, msg)


class Api:
    def __init__(self):
        rotate_log_if_needed()   # cắt bớt nhật ký cũ nếu đã quá lớn, trước khi ghi thêm
        # Cho requests/ssl tin kho chứng chỉ Windows: proxy soi SSL của công ty
        # hết làm hỏng lời gọi HTTPS mà không phải tắt xác thực. Best-effort.
        net.install_truststore()
        self._window = None
        self._cfg = AppConfig.load()
        self._engine = None
        self._engine_thread = None
        self._last_download_result = None
        self._lock = threading.Lock()
        self._log_history = []

        # --- Kết nối cơ sở dữ liệu dùng chung ---
        self._db_conn = None
        self._db_conn_path = None
        self._db_lock = threading.RLock()
        # Khác _db_lock (chỉ bảo vệ con trỏ connection), khóa này giữ trọn một API
        # nhiều truy vấn để start_download không đóng DB ở giữa báo cáo/danh sách.
        self._db_access_lock = threading.RLock()
        self._candidate_cache = {}
        self._report_cache = {}
        self._report_cache_at = {}
        self._filter_options_cache = None
        self._data_stats_cache = None
        self._checkpoint_cache = {}
        self._exclusive_db_owner = False

        # --- Hàng đợi cập nhật giao diện (xem _flush_ui) ---
        self._ui_logs = []
        self._file_logs = []
        self._persist_logs = []
        self._ui_progress = None
        self._ui_candidates = []
        self._ui_lock = threading.Lock()
        self._ui_stop = threading.Event()
        self._ui_thread = None

        # --- Hẹn giờ ---
        self._scheduler_thread = None
        self._scheduler_stop = threading.Event()
        self._scheduler_next_run = None
        self._scheduler_job_next = {}
        #: Mốc giờ chạy gốc của từng lịch (parse một lần từ `start_time`), dùng
        #: để tính giờ chạy tiếp theo trên một LƯỚI CỐ ĐỊNH `anchor + k*interval`
        #: - không tính từ lúc lượt trước KẾT THÚC, để tránh trôi giờ khi một
        #: lượt chạy lâu (vd JobsGO quét toàn bộ hồ sơ).
        self._scheduler_job_anchor = {}
        self._parsing = CvParsingService(
            self._cfg, lambda: Database(self._cfg.db_path, log=self.log).open(), self.log,
            on_finish=self._push_parsing_status)

        # --- Đồng bộ lên Hub ---
        self._sync = SyncService(self)

        # --- Điều phối pipeline: Tải -> Parsing -> Đồng bộ ---
        # Tự chạy parsing/đồng bộ theo delta và cho các tầng nhường máy lẫn nhau.
        # Khởi động thật sự trong set_window() để các lần đẩy trạng thái sang UI
        # có cửa sổ để bám vào.
        self._coordinator = PipelineCoordinator(self)

    # ---------------- Cơ sở dữ liệu dùng chung ----------------
    def _db(self):
        """Trả về MỘT kết nối cơ sở dữ liệu dùng chung cho cả vòng đời chương trình.

        Trước đây mỗi thao tác trên giao diện (xem thống kê, lọc, sang trang, đổi tab,
        và cả MỖI DÒNG nhật ký khi đang tải CV) đều mở rồi đóng một kết nối mới. Khi
        cơ sở dữ liệu nằm trong thư mục Google Drive, riêng việc mở kết nối đã mất
        khoảng 0,7 giây - nên mỗi cú bấm chuột phải chờ gần một giây, và mỗi CV tải về
        bị cộng thêm chừng ấy thời gian chỉ để ghi một dòng nhật ký.

        Giữ sẵn một kết nối thì các thao tác sau đó gần như tức thì. An toàn khi nhiều
        luồng cùng dùng vì lớp Database đã tự khoá quanh mọi câu lệnh, và kết nối được
        tạo với check_same_thread=False. Nếu người dùng đổi đường dẫn ở tab Cấu hình,
        hàm này tự phát hiện và mở lại đúng cơ sở dữ liệu mới.
        """
        with self._db_lock:
            path = self._cfg.db_path
            if ((self._exclusive_db_owner or self._parsing.running())
                    and is_cloud_synced_path(path)):
                raise sqlite3.OperationalError(
                    "CSDL trên ổ đĩa đám mây đang được tiến trình đồng bộ sử dụng độc quyền.")
            if (self._db_conn is not None and self._db_conn_path == path
                    and self._db_conn.conn is not None):
                return self._db_conn
            self._close_db()
            self._db_conn = Database(path).open()
            self._db_conn_path = path
            account_map = {
                "topcv": getattr(self._cfg, "email", ""),
                "vietnamworks": getattr(self._cfg, "vietnamworks_email", ""),
                "careerviet": getattr(self._cfg, "careerviet_email", ""),
                "vieclam24h": getattr(self._cfg, "vieclam24h_email", ""),
                "itviec": getattr(self._cfg, "itviec_email", ""),
                "joboko": getattr(self._cfg, "joboko_email", ""),
                "jobsgo": getattr(self._cfg, "jobsgo_email", ""),
            }
            self._db_conn.backfill_accounts(account_map)
            # Tắt máy giữa lúc đang gửi sẽ để lại hàng ở trạng thái inflight mà
            # không còn ai gửi. Không nhặt lại thì chúng kẹt vĩnh viễn.
            try:
                recovered = self._db_conn.recover_sync_queue()
                if recovered:
                    self.log(f"Đã khôi phục {recovered} bản ghi đồng bộ dở dang.")
            except sqlite3.Error:
                pass
            return self._db_conn

    def _close_db(self):
        with self._db_lock:
            if self._db_conn is not None:
                try:
                    self._db_conn.close()
                except Exception:
                    pass
            self._db_conn = None
            self._db_conn_path = None

    def set_window(self, window):
        self._window = window
        self._start_ui_flusher()
        self._coordinator.start()

    def _push_parsing_status(self):
        """Đẩy trạng thái parsing sang giao diện ngay khi một lượt kết thúc.

        Bản cũ chỉ cập nhật dict trong RAM nên nếu người dùng rời tab Parsing thì
        vòng poll ngừng và nút "Dừng parsing" kẹt lại dù đã xong."""
        try:
            status = self.get_cv_parsing_status()
            self._eval("window.app && window.app.onParsingStatus("
                       f"{json.dumps(status, ensure_ascii=False)});")
        except Exception:
            pass

    def get_app_info(self):
        return {"version": APP_VERSION, "display_name": APP_DISPLAY_NAME}

    def report_packaged_startup_ready(self, readiness=None, initial_data_ready=False):
        """JS bridge handshake dùng riêng cho post-build probe."""
        if os.environ.get("MSB_RADAR_PACKAGED_STARTUP_PROBE") != "1":
            return {"ok": True, "probe": False}
        if not isinstance(readiness, dict) or not readiness.get("ok"):
            return {"ok": False, "error": "Runtime readiness chưa đạt yêu cầu."}
        if not initial_data_ready:
            return {"ok": False, "error": "Dữ liệu khởi tạo chưa tải thành công."}
        marker = os.environ.get("MSB_RADAR_PACKAGED_STARTUP_MARKER", "")
        runtime_dir = os.path.abspath(os.environ.get("MSB_RADAR_RUNTIME_DIR", ""))
        if not marker or not runtime_dir:
            return {"ok": False, "error": "Thiếu đường dẫn startup marker."}
        marker_path = os.path.abspath(marker)
        if os.path.commonpath((marker_path, runtime_dir)) != runtime_dir:
            return {"ok": False, "error": "Startup marker nằm ngoài thư mục probe."}
        with open(marker_path, "w", encoding="utf-8") as stream:
            stream.write("JS bridge and runtime readiness completed\n")
        return {"ok": True, "probe": True}

    def _eval(self, js_code):
        if self._window:
            try:
                self._window.evaluate_js(js_code)
            except Exception as e:
                print("JS Eval Error:", e)

    # ---------------- Gom lô cập nhật giao diện ----------------
    # evaluate_js() gọi từ luồng nền sang luồng giao diện và CHẶN cho tới khi trình duyệt
    # chạy xong. Trước đây mỗi dòng nhật ký và mỗi nhịp tiến độ đều gọi thẳng một lần:
    # tải 23.000 CV là hơn 50.000 lượt chặn -> cửa sổ đứng hình, Windows báo
    # "Not Responding". Giờ mọi cập nhật được xếp hàng, một luồng nền cứ 1/4 giây gom
    # lại đẩy sang giao diện ĐÚNG MỘT LẦN. Riêng tiến độ chỉ giữ bản mới nhất - các nhịp
    # cũ không còn ý nghĩa gì nên bỏ luôn thay vì đẩy hết sang.
    UI_FLUSH_SEC = 0.25

    def _start_ui_flusher(self):
        if self._ui_thread and self._ui_thread.is_alive():
            return

        def loop():
            while not self._ui_stop.is_set():
                time.sleep(self.UI_FLUSH_SEC)
                try:
                    self._flush_ui()
                except Exception as e:
                    print("UI flush error:", e)

        self._ui_stop.clear()
        self._ui_thread = threading.Thread(target=loop, daemon=True)
        self._ui_thread.start()

    def _flush_ui(self, force_persist=False):
        downloading = bool((self._engine_thread and self._engine_thread.is_alive())
                           or self._parsing.running())
        with self._ui_lock:
            logs, self._ui_logs = self._ui_logs, []
            file_logs, self._file_logs = self._file_logs, []
            if force_persist or not downloading:
                persist_logs, self._persist_logs = self._persist_logs, []
            else:
                persist_logs = []
            prog, self._ui_progress = self._ui_progress, None
            candidates, self._ui_candidates = self._ui_candidates, []
        if logs:
            self._eval(f"window.app && window.app.addLogBatch({json.dumps(logs)});")
        if file_logs:
            try:
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write("\n".join(file_logs) + "\n")
            except Exception:
                with self._ui_lock:
                    self._file_logs[0:0] = file_logs
        # Không ghi app_logs khi engine đang ghi candidates. Hai kết nối SQLite cùng
        # tranh quyền ghi trên Google Drive là nguyên nhân chính làm tải CV và log ì.
        # Toàn bộ log vẫn hiện real time; phần lịch sử được ghi một lô ngay khi chạy xong.
        if persist_logs:
            try:
                with self._db_access_lock:
                    db = self._db()
                    db.insert_logs(persist_logs)
                    db.commit()
            except Exception:
                with self._ui_lock:
                    self._persist_logs[0:0] = persist_logs
        if prog is not None:
            self._eval(f"window.app && window.app.updateProgress({json.dumps(prog)});")
        if candidates:
            self._eval(
                f"window.app && window.app.onCandidateBatch({json.dumps(candidates)});")

    def log(self, text: str, level: str = "INFO", source: str = "system"):
        # Đồng bộ Hub chạy nền độc lập với luồng tải CV đang hiển thị trên màn
        # hình; không gắn nhãn thì lỗi của một tài khoản/kênh khác (vd Joboko)
        # lẫn vào log của kênh người dùng đang xem (vd JobsGO) và bị hiểu nhầm.
        if source == "sync":
            text = f"[Đồng bộ Hub] {text}"
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
        try:
            print(line)
        except Exception:
            try:
                sys.stdout.buffer.write((line + "\n").encode("utf-8", errors="replace"))
                sys.stdout.buffer.flush()
            except Exception:
                pass
        if "LỖI" in text or "✗" in text or "Exception" in text:
            level = "ERROR"
        elif "✓" in text or "KẾT QUẢ" in text:
            level = "SUCCESS"

        # Cả giao diện, file và SQLite đều được gom lô; log() không còn chặn luồng tải.
        with self._ui_lock:
            self._log_history.append(line)
            if len(self._log_history) > 1000:
                del self._log_history[:-1000]
            self._ui_logs.append(line)
            self._file_logs.append(line)
            self._persist_logs.append(
                (source, level, text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    def get_recent_logs(self, limit=300):
        """Đọc lại N dòng cuối trong nhatky.log."""
        try:
            if not os.path.exists(LOG_PATH):
                return []
            with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return [ln.rstrip("\n") for ln in lines[-int(limit):]]
        except Exception:
            return []

    @serialized_db_api
    def get_history_logs(self, filters=None):
        """Tra cứu lịch sử nhật ký quá khứ từ CSDL SQLite có phân trang và bộ lọc."""
        filters = filters or {}
        limit = int(filters.get("limit", 200))
        offset = int(filters.get("offset", 0))
        level = str(filters.get("level", "")).strip()
        search = str(filters.get("search", "")).strip()

        try:
            items, total = self._db().query_logs(
                limit=limit, offset=offset, level=level, search=search)
            return {"items": items, "total": total}
        except Exception as e:
            return {"items": [], "total": 0, "error": str(e)}

    def _on_progress(self, p):
        # Xếp hàng - chỉ giữ bản MỚI NHẤT (các nhịp cũ hơn không còn ý nghĩa gì, không
        # cần đẩy hết sang giao diện). Luồng gom lô trong _flush_ui() sẽ gửi định kỳ.
        data = {
            "phase": p.phase,
            "done": p.done,
            "total": p.total,
            "new": p.new,
            "skipped": p.skipped,
            "failed": p.failed,
            "eta_sec": p.eta_sec,
            "stored_total": p.stored_total,
            "stored_done": p.stored_done,
            "stored_failed": p.stored_failed
        }
        with self._ui_lock:
            self._ui_progress = data

    def _on_candidate(self, item, is_new):
        """Đưa bản ghi vừa xử lý sang UI qua RAM; không đọc lại SQLite cloud."""
        payload = {key: (item.get(key) if item.get(key) is not None else "")
                   for key, _label in EXPORT_COLUMNS if key != "alerts"}
        payload["applied_ts"] = item.get("applied_ts") or ""
        payload["is_new"] = bool(is_new)
        payload["alerts"] = ""
        payload["alerts_short"] = ""
        # Cập nhật snapshot trang đầu đang cache để JS có thể render lại từ RAM.
        for key, cached in list(self._candidate_cache.items()):
            (limit, offset, search, source, account, dl_status, _position,
             date_from, date_to, sort_by, sort_dir) = key
            if offset or sort_by != "applied_ts" or sort_dir != "DESC":
                continue
            if source and payload.get("source") not in source:
                continue
            if account and payload.get("account") not in account:
                continue
            if dl_status == "done" and payload.get("dl_status") != DONE:
                continue
            if dl_status == "failed" and payload.get("dl_status") == DONE:
                continue
            applied_date = str(payload.get("applied_ts") or "")[:10]
            if date_from and applied_date < date_from:
                continue
            if date_to and applied_date > date_to:
                continue
            if search and not any(search.lower() in str(value).lower()
                                  for value in payload.values()):
                continue
            identity = (payload.get("source"), payload.get("account"), payload.get("cv_id"))
            old_items = cached.get("items", [])
            existed = any((row.get("source"), row.get("account"), row.get("cv_id")) == identity
                          for row in old_items)
            cached["items"] = ([payload] + [row for row in old_items
                                             if (row.get("source"), row.get("account"),
                                                 row.get("cv_id")) != identity])[:limit]
            if is_new and not existed:
                cached["total"] = int(cached.get("total") or 0) + 1
                self._increment_breakdown(cached, "by_source", payload.get("source") or "unknown")
                year = applied_date[:4] if (len(applied_date) >= 4 and applied_date[:4].isdigit()) \
                    else "Không rõ năm"
                self._increment_breakdown(cached, "by_year", year)
        with self._ui_lock:
            if is_new and getattr(self, "_data_stats_cache", None) is not None:
                self._data_stats_cache["total"] = int(
                    self._data_stats_cache.get("total") or 0) + 1
                status_key = "done" if payload.get("dl_status") == DONE else "failed"
                self._data_stats_cache[status_key] = int(
                    self._data_stats_cache.get(status_key) or 0) + 1
            self._ui_candidates.append(payload)
            # Giới hạn RAM nếu webview tạm thời không nhận được sự kiện.
            if len(self._ui_candidates) > 500:
                del self._ui_candidates[:-500]

    @staticmethod
    def _increment_breakdown(cached, field, value):
        rows = cached.setdefault(field, [])
        for row in rows:
            if row.get("value") == value:
                row["count"] = int(row.get("count") or 0) + 1
                return
        rows.append({"value": value, "count": 1})

    # ================= CẤU HÌNH =================
    def get_config(self):
        data = asdict(self._cfg)
        sources = ("topcv", "vietnamworks", "careerviet", "vieclam24h", "itviec", "joboko", "jobsgo")
        for field_name in ("password", "vietnamworks_password", "careerviet_password",
                           "vieclam24h_password", "itviec_password"):
            data.pop(field_name, None)
        data["password_status"] = {
            source: self._cfg.has_password(source) for source in sources
        }
        data["config_warning"] = getattr(self._cfg, "_load_warning", "")
        data["provider_accounts"] = [
            {**row, "has_password": self._account_has_password(row)}
            for row in self._cfg.provider_accounts]
        data["schedule_jobs"] = list(self._cfg.schedule_jobs)
        return data

    def get_runtime_readiness(self):
        return runtime_readiness()

    def save_schedule_job(self, job):
        import uuid
        valid_sources = {"topcv", "vietnamworks", "careerviet", "vieclam24h", "itviec", "joboko", "jobsgo"}
        sources = [str(source) for source in job.get("sources", []) if source in valid_sources]
        interval = max(15, min(10080, int(job.get("interval_min") or 60)))
        if not sources:
            return {"ok": False, "error": "Hãy chọn ít nhất một kênh tuyển dụng."}
        if job.get("mode") not in ("moi", "tatca"):
            return {"ok": False, "error": "Chế độ quét không hợp lệ."}
        name = str(job.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "Hãy đặt tên để dễ nhận biết lịch."}
        start_time = str(job.get("start_time") or "").strip()
        try:
            self._parse_schedule_start(start_time)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Thời điểm chạy lần đầu không hợp lệ."}
        valid_account_ids = {row.get("id") for row in self._cfg.provider_accounts
                             if row.get("source") in sources and row.get("enabled", True)}
        unavailable = [source for source in sources if not self._cfg.accounts_for_source(source)]
        if job.get("enabled", True) and unavailable:
            return {"ok": False, "error": "Chưa có tài khoản đang bật cho: " + ", ".join(unavailable)}
        clean = {"id": str(job.get("id") or uuid.uuid4().hex[:12]),
                 "name": name[:100],
                 "sources": sources,
                 "account_ids": [value for value in job.get("account_ids", [])
                                 if value in valid_account_ids],
                 "mode": job.get("mode"), "interval_min": interval,
                 "start_time": start_time,
                 "enabled": bool(job.get("enabled", True)), "last_run_at": "",
                 "last_status": "Chưa chạy", "fail_streak": 0}
        existing = next((i for i, row in enumerate(self._cfg.schedule_jobs)
                         if row.get("id") == clean["id"]), None)
        if existing is None:
            self._cfg.schedule_jobs.append(clean)
        else:
            clean["last_run_at"] = self._cfg.schedule_jobs[existing].get("last_run_at", "")
            clean["last_status"] = self._cfg.schedule_jobs[existing].get("last_status", "Chưa chạy")
            # Người dùng vừa chủ động sửa lịch (vd cập nhật mật khẩu tài khoản) -
            # coi như một khởi đầu mới, không giữ số lần lỗi liên tiếp cũ để
            # lịch không bị kẹt ở khoảng nghỉ giãn cách của lần lỗi trước đó.
            clean["fail_streak"] = 0
            self._cfg.schedule_jobs[existing] = clean
        # Lịch đang chạy (nếu có) phải làm mới mốc gốc theo start_time vừa lưu,
        # để lưới giờ chạy tiếp theo (anchor + k*interval) không dùng nhầm mốc
        # cũ khi người dùng vừa đổi start_time/interval của một lịch đang bật.
        self._scheduler_job_anchor.pop(clean["id"], None)
        self._scheduler_job_next.pop(clean["id"], None)
        self._cfg.save()
        return {"ok": True, "job": clean}

    def delete_schedule_job(self, job_id):
        self._cfg.schedule_jobs = [job for job in self._cfg.schedule_jobs if job.get("id") != job_id]
        self._scheduler_job_next.pop(job_id, None)
        self._scheduler_job_anchor.pop(job_id, None)
        self._cfg.save()
        return {"ok": True}

    def run_schedule_job_now(self, job_id):
        job = next((row for row in self._cfg.schedule_jobs if row.get("id") == job_id), None)
        if not job:
            return {"ok": False, "error": "Không tìm thấy lịch."}
        if not job.get("enabled", True):
            return {"ok": False, "error": "Hãy bật lịch này trước khi chạy."}
        if not (self._scheduler_thread and self._scheduler_thread.is_alive()):
            result = self.start_schedule()
            if not result.get("ok"):
                return result
        self._scheduler_job_next[job_id] = datetime.now()
        self._scheduler_next_run = datetime.now()
        return {"ok": True}

    @staticmethod
    def _account_secret_key(account_id):
        return "account:" + str(account_id or "")

    def _account_has_password(self, account):
        from .config import SECRET_PATH
        from .secrets import SecretStore
        if SecretStore(SECRET_PATH).has(self._account_secret_key(account.get("id"))):
            return True
        return (account_for_source(self._cfg, account.get("source")) == account.get("email")
                and self._cfg.has_password(account.get("source")))

    def save_provider_account(self, account):
        try:
            source = str(account.get("source") or "").strip()
            email = str(account.get("email") or "").strip().lower()
            if source not in ("topcv", "vietnamworks", "careerviet", "vieclam24h", "itviec", "joboko", "jobsgo") or not email:
                return {"ok": False, "error": "Nguồn và email tài khoản là bắt buộc."}
            import hashlib
            account_id = str(account.get("id") or hashlib.sha256(
                f"{source}:{email}".encode()).hexdigest()[:12])
            if any(row.get("source") == source and row.get("email") == email and
                   row.get("id") != account_id for row in self._cfg.provider_accounts):
                return {"ok": False, "error": "Tài khoản này đã tồn tại trong nguồn đã chọn."}
            clean = {"id": account_id, "source": source, "email": email,
                     "label": str(account.get("label") or email).strip(),
                     "enabled": bool(account.get("enabled", True))}
            previous = [dict(row) for row in self._cfg.provider_accounts]
            updated = [dict(row) for row in previous]
            existing = next((i for i, row in enumerate(updated)
                             if row.get("id") == account_id), None)
            if existing is None:
                updated.append(clean)
            else:
                updated[existing] = clean
            self._cfg.provider_accounts = updated
            try:
                password = str(account.get("password") or "")
                if password:
                    from .config import SECRET_PATH
                    from .secrets import SecretStore
                    SecretStore(SECRET_PATH).set(self._account_secret_key(account_id), password)
                self._cfg.save()
            except Exception:
                self._cfg.provider_accounts = previous
                raise
            return {"ok": True,
                    "account": {**clean, "has_password": self._account_has_password(clean)},
                    "needs_setup": self.needs_setup()}
        except Exception as exc:
            return {"ok": False,
                    "error": f"Không ghi được cấu hình tài khoản: {str(exc)[:180]}"}

    def delete_provider_account(self, account_id):
        account = next((row for row in self._cfg.provider_accounts if row.get("id") == account_id), None)
        if not account:
            return {"ok": False, "error": "Không tìm thấy tài khoản."}
        if self.is_downloading():
            return {"ok": False, "error": "Không thể xóa tài khoản khi đang đồng bộ."}
        
        source = account.get("source", "topcv")
        deleted_email = normalize_account(account.get("email"))

        # Xóa khỏi danh sách provider_accounts
        self._cfg.provider_accounts = [row for row in self._cfg.provider_accounts
                                       if row.get("id") != account_id]
        
        # Xóa bí mật của tài khoản
        from .config import SECRET_PATH
        from .secrets import SecretStore
        secret_store = SecretStore(SECRET_PATH)
        secret_store.set(self._account_secret_key(account_id), "")

        # Đồng bộ lại trường legacy email & password nếu cần
        field = {"topcv": "email", "vietnamworks": "vietnamworks_email",
                 "careerviet": "careerviet_email", "vieclam24h": "vieclam24h_email",
                 "itviec": "itviec_email", "joboko": "joboko_email",
                 "jobsgo": "jobsgo_email"}.get(source, "email")
        pw_field = "password" if source == "topcv" else f"{source}_password"

        remaining_for_source = [row for row in self._cfg.provider_accounts if row.get("source") == source]
        if normalize_account(getattr(self._cfg, field, "")) == deleted_email:
            if remaining_for_source:
                new_main_account = remaining_for_source[0]
                setattr(self._cfg, field, new_main_account.get("email", ""))
                pw = secret_store.get(self._account_secret_key(new_main_account.get("id", "")))
                if pw:
                    secret_store.set(pw_field, pw)
            else:
                setattr(self._cfg, field, "")
                secret_store.set(pw_field, "")

        # Dọn dẹp id trong các lịch hẹn giờ schedule_jobs
        for job in self._cfg.schedule_jobs:
            if "account_ids" in job and account_id in job.get("account_ids", []):
                job["account_ids"] = [aid for aid in job["account_ids"] if aid != account_id]

        self._cfg.save()
        return {"ok": True}

    def clear_provider_password(self, provider_id="topcv"):
        fields = {
            "topcv": "password", "vietnamworks": "vietnamworks_password",
            "careerviet": "careerviet_password", "vieclam24h": "vieclam24h_password",
            "itviec": "itviec_password", "joboko": "joboko_password", "jobsgo": "jobsgo_password",
        }
        field = fields.get(provider_id)
        if not field:
            return {"ok": False, "error": "Nguồn tuyển dụng không hợp lệ."}
        setattr(self._cfg, field, "")
        from .config import SECRET_PATH
        from .secrets import SecretStore
        SecretStore(SECRET_PATH).set(field, "")
        self._cfg.save()
        return {"ok": True}

    def needs_setup(self):
        # The account editor stores credentials per account (account:<id>), while
        # AppConfig.needs_setup() validates only the legacy single-account fields.
        # Once the new account model is in use, an enabled account with a stored
        # password is the source of truth for first-run readiness.
        if self._cfg.provider_accounts:
            enabled_accounts = (
                account for account in self._cfg.provider_accounts
                if account.get("enabled", True) and str(account.get("email") or "").strip()
            )
            return not any(self._account_has_password(account) for account in enabled_accounts)
        return self._cfg.needs_setup()

    def validate_provider_config(self, provider_id="topcv", account_id=""):
        account = next((row for row in self._cfg.accounts_for_source(provider_id)
                        if row.get("id") == account_id), None)
        if not account:
            return {"ok": False, "errors": ["Tài khoản vận hành không hợp lệ hoặc đang tắt."]}
        errors = self._cfg.for_account(account).validate(provider_id)
        return {"ok": not errors, "errors": errors}

    @serialized_db_api
    def get_system_health(self):
        try:
            if self.is_downloading() or self._parsing.running():
                return {"ok": True, "busy": True}
            db = self._db()
            health = db.health()
            usage = shutil.disk_usage(os.path.dirname(self._cfg.db_path) or app_dir())
            provider_profiles = {}
            for source in ("topcv", "vietnamworks", "careerviet", "vieclam24h", "itviec", "joboko", "jobsgo"):
                target = self._provider_browser_target(source)
                provider_profiles[source] = bool(
                    target and profile_browser_processes(target[0]()))
            health.update({
                "ok": health["quick_check"].lower() == "ok",
                "database_path": self._cfg.db_path,
                "free_bytes": usage.free,
                "last_backup": db.get_meta("last_backup_at", ""),
                "profiles_open": provider_profiles,
            })
            stats = db.stats()
            health["done"] = stats["done"]
            health["failed"] = stats["failed"]
            last_backup = health["last_backup"]
            try:
                health["backup_age_hours"] = round(
                    (datetime.now() - datetime.strptime(last_backup, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600, 1)
            except (TypeError, ValueError):
                health["backup_age_hours"] = None
            return health
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @serialized_db_api
    def backup_database(self):
        if self.is_downloading() or self._parsing.running():
            return {"ok": False, "error": "Không sao lưu trong lúc đang đồng bộ; hãy đợi lượt tải hoàn tất."}
        try:
            db = self._db()
            folder = os.path.join(os.path.dirname(self._cfg.db_path), "MSB_Radar_Backup")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = os.path.join(folder, f"msbradar_{stamp}.db")
            db.backup_to(target)
            db.set_meta("last_backup_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            db.commit()
            return {"ok": True, "path": target}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @serialized_db_api
    def delete_candidate_data(self, filters=None, confirmation=""):
        filters = filters or {}
        if confirmation != "XOA DU LIEU":
            return {"ok": False, "error": "Mã xác nhận không hợp lệ."}
        if not any(filters.get(key) for key in ("source", "account", "date_from", "date_to")):
            return {"ok": False, "error": "Phải chọn ít nhất một phạm vi xóa."}
        if self.is_downloading() or self._parsing.running():
            return {"ok": False, "error": "Không thể xóa dữ liệu trong lúc đang đồng bộ."}
        try:
            db = self._db()
            rows = db.delete_candidates(
                source=str(filters.get("source") or ""),
                account=str(filters.get("account") or ""),
                date_from=str(filters.get("date_from") or ""),
                date_to=str(filters.get("date_to") or ""))
            cv_root = os.path.normcase(os.path.abspath(self._cfg.cv_folder))
            removed_files = 0
            for row in rows:
                filename = row.get("filename") or ""
                if not filename:
                    continue
                path = os.path.normcase(os.path.abspath(os.path.join(cv_root, filename)))
                if os.path.commonpath([cv_root, path]) != cv_root:
                    continue
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                        removed_files += 1
                except OSError:
                    pass
            db.commit()
            return {"ok": True, "rows": len(rows), "files": removed_files}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_provider_browser(self, provider_id="topcv", account_id=""):
        """Mở Chrome thường với đúng profile nguồn/tài khoản để thao tác thủ công."""
        account = next((row for row in self._cfg.accounts_for_source(provider_id, False)
                        if not account_id or row.get("id") == account_id), None)
        runtime_cfg = self._cfg.for_account(account) if account else self._cfg
        target = self._provider_browser_target(provider_id, runtime_cfg)
        if not target:
            return {"ok": False, "error": "Nguồn tuyển dụng không hợp lệ."}
        with self._lock:
            if self._engine_thread and self._engine_thread.is_alive():
                return {"ok": False, "error": (
                    "Đang có tiến trình đồng bộ CV. Không thể mở Chrome profile cho tới khi hoàn tất hoặc dừng.")}
        try:
            profile_dir = target[0]()
            open_profile_browser(profile_dir, target[1])
            return {"ok": True, "profile": profile_dir}
        except ChromeStartError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"Không mở được trình duyệt: {str(exc)[:160]}"}

    def _provider_browser_target(self, provider_id, cfg=None):
        cfg = cfg or self._cfg
        providers = {
            "topcv": (cfg.profile_dir, "https://tuyendung.topcv.vn/app/cvs-management"),
            "vietnamworks": (cfg.vietnamworks_profile_dir,
                             "https://employer.vietnamworks.com/v2/job/default/index"),
            "careerviet": (cfg.careerviet_profile_dir,
                           "https://careerviet.vn/vi/employers/hrcentral/manageresume"),
            "vieclam24h": (cfg.vieclam24h_profile_dir,
                           "https://ntd.vieclam24h.vn/bang-tin.html"),
            "itviec": (cfg.itviec_profile_dir,
                       "https://itviec.com/customer/job-applications"),
            "joboko": (cfg.joboko_profile_dir, "https://em-vn.joboko.com/cv"),
            "jobsgo": (cfg.jobsgo_profile_dir, "https://employer.jobsgo.vn/candidate/all"),
        }
        return providers.get(provider_id)

    def save_config(self, config_dict):
        try:
            if self._parsing.running():
                protected = {"cv_folder", "db_path", "parsing_max_pages", "parsing_max_file_mb"}
                if any(key in config_dict and config_dict[key] != getattr(self._cfg, key)
                       for key in protected):
                    return {"ok": False, "error": "Hãy dừng parsing trước khi đổi đường dẫn hoặc giới hạn xử lý."}
            if "schedule_interval_min" in config_dict:
                interval = int(config_dict["schedule_interval_min"])
                if interval < 5:
                    return {"ok": False, "error": "Tần suất lặp lại phải từ 5 phút trở lên."}
            if config_dict.get("schedule_mode", self._cfg.schedule_mode) not in ("moi", "tatca"):
                return {"ok": False, "error": "Chế độ quét hẹn giờ không hợp lệ."}
            valid_sources = ("topcv", "vietnamworks", "careerviet", "vieclam24h", "itviec", "joboko", "jobsgo")
            schedule_sources = config_dict.get("schedule_sources") or [
                config_dict.get("schedule_source", self._cfg.schedule_source)]
            if any(source not in valid_sources for source in schedule_sources):
                return {"ok": False, "error": "Nguồn hẹn giờ không hợp lệ."}
            schedule_start = str(config_dict.get(
                "schedule_start_time", self._cfg.schedule_start_time) or "").strip()
            if schedule_start:
                self._parse_schedule_start(schedule_start)

            old_interval = self._cfg.schedule_interval_min
            old_mode = self._cfg.schedule_mode
            old_source = self._cfg.schedule_source
            old_sources = list(self._cfg.schedule_sources)
            old_start = self._cfg.schedule_start_time
            was_running = bool(self._scheduler_thread and self._scheduler_thread.is_alive()
                               and not self._scheduler_stop.is_set())
            for k, v in config_dict.items():
                if hasattr(self._cfg, k):
                    if k.endswith("password") and not v:
                        continue
                    target_type = type(getattr(self._cfg, k))
                    if target_type is int:
                        v = int(v)
                    elif target_type is bool:
                        v = bool(v)
                    setattr(self._cfg, k, v)
            self._cfg.save()
            desired_running = bool(self._cfg.schedule_enabled)
            schedule_changed = (
                old_interval != self._cfg.schedule_interval_min
                or old_mode != self._cfg.schedule_mode
                or old_source != self._cfg.schedule_source
                or old_sources != self._cfg.schedule_sources
                or old_start != self._cfg.schedule_start_time)
            if desired_running and not was_running:
                result = self.start_schedule()
                if not result.get("ok"):
                    return result
            elif not desired_running and was_running:
                self.stop_schedule()
            elif was_running and schedule_changed:
                # Áp dụng ngay cấu hình lịch mới và cập nhật đồng hồ giao diện.
                self._scheduler_next_run = datetime.now() + timedelta(
                    minutes=max(5, int(self._cfg.schedule_interval_min)))
                next_str = self._scheduler_next_run.strftime("%Y-%m-%d %H:%M:%S")
                self._eval(f"window.app && window.app.onScheduleNextRun({json.dumps(next_str)});")
            self.log("Đã lưu cấu hình thành công.")
            schedule_text = (f"Hẹn giờ đang bật, lặp mỗi {self._cfg.schedule_interval_min} phút."
                             if desired_running else "Hẹn giờ đang tắt.")
            notify("MSB Radar Edge", f"Cấu hình đã được lưu thành công. {schedule_text}")
            return {"ok": True, "schedule_applied": desired_running}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def select_cv_folder(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(initialdir=self._cfg.cv_folder or os.path.expanduser("~"))
        root.destroy()
        if folder:
            self._cfg.cv_folder = folder
            self._cfg.save()
            return folder
        return self._cfg.cv_folder

    def select_db_path(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(self._cfg.db_path) or os.path.expanduser("~"),
            initialfile=os.path.basename(self._cfg.db_path),
            defaultextension=".db",
            filetypes=[("SQLite Database", "*.db"), ("All Files", "*.*")]
        )
        root.destroy()
        if path:
            self._cfg.db_path = path
            self._cfg.save()
            return path
        return self._cfg.db_path

    def select_open_file(self, purpose=""):
        """Hộp thoại chọn MỘT file có sẵn (CA nội bộ, chromedriver...). Chỉ trả
        đường dẫn, KHÔNG tự lưu cấu hình - việc lưu do nút Lưu Cấu Hình lo."""
        specs = {
            "ca_bundle": ("Chọn file chứng chỉ CA nội bộ",
                          [("Chứng chỉ", "*.pem *.crt *.cer"), ("Tất cả", "*.*")],
                          getattr(self._cfg, "ssl_ca_bundle", "")),
            "chromedriver": ("Chọn chromedriver.exe",
                             [("chromedriver", "chromedriver*.exe"), ("Tất cả", "*.*")],
                             getattr(self._cfg, "chromedriver_path", "")),
        }
        title, filetypes, current = specs.get(
            purpose, ("Chọn file", [("Tất cả", "*.*")], ""))
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title=title,
            initialdir=os.path.dirname(current) if current else os.path.expanduser("~"),
            filetypes=filetypes)
        root.destroy()
        return path or ""

    # ================= NGUỒN & TẢI CV =================
    def get_providers(self):
        providers = {p.key: p for p in ALL_PROVIDERS}
        res = []
        for account in self._cfg.provider_accounts:
            if account.get("enabled", True) is False:
                continue
            provider = providers.get(account.get("source"))
            if not provider:
                continue
            res.append({
                "id": provider.key,
                "account_id": account.get("id"),
                "email": account.get("email", ""),
                "display_name": account.get("label") or account.get("email") or provider.display_name,
                "provider_name": provider.display_name,
                "is_enabled": getattr(provider, "available", True),
                "is_experimental": not getattr(provider, "available", True),
            })
        return res

    @serialized_db_api
    def get_checkpoint(self, provider_id="topcv", account_id=""):
        cache_key = f"{provider_id}:{account_id}"
        if ((getattr(self, "_exclusive_db_owner", False)
             or self.is_downloading() or self._parsing.running())
                and is_cloud_synced_path(self._cfg.db_path)):
            cached = dict(self._checkpoint_cache.get(cache_key) or {
                "last_page": 0, "next_page": 0, "total_pages": 0,
                "start_page": 1, "end_page": 0, "reverse": False,
                "has_more": False, "timestamp": "",
            })
            cached.update({"stale": True, "busy": True})
            return cached
        db = self._db()
        import hashlib
        account_row = next((row for row in self._cfg.accounts_for_source(provider_id)
                            if row.get("id") == account_id), None)
        if not account_row:
            return {"last_page": 0, "next_page": 0, "total_pages": 0,
                    "start_page": 1, "end_page": 0, "reverse": False,
                    "has_more": False, "timestamp": "", "error": "Tài khoản vận hành không hợp lệ."}
        account = str(account_row.get("email") or "").strip().lower()
        account_key = hashlib.sha256(account.encode("utf-8")).hexdigest()[:12]
        prefix = f"checkpoint_{provider_id}_{account_key}_"
        last_page = db.get_meta(prefix + "last_page", "0")
        reverse = db.get_meta(prefix + "reverse", "0") == "1"
        # Tương thích checkpoint của bản cũ: chưa có next_page thì suy ra trang kế tiếp.
        default_next = max(1, int(last_page or 0) + (-1 if reverse else 1))
        next_page = db.get_meta(prefix + "next_page", str(default_next))
        total_pages = db.get_meta(prefix + "total_pages", "0")
        start_page = db.get_meta(prefix + "start_page", "1")
        end_page = db.get_meta(prefix + "end_page", total_pages or "0")
        has_more_raw = db.get_meta(prefix + "has_more", None)
        # Bản cũ chưa có has_more: chỉ coi là còn dở khi trang kế tiếp vẫn
        # nằm trong chính phạm vi đã chọn, tránh hiện nút Tiếp tục sau khi xong.
        inferred_end = int(end_page or total_pages or 0)
        inferred_next = int(next_page or 0)
        has_more = ((int(start_page or 1) <= inferred_next <= inferred_end)
                    if has_more_raw is None else has_more_raw == "1")
        timestamp = db.get_meta(prefix + "timestamp", "")
        result = {
            "last_page": int(last_page or 0),
            "next_page": int(next_page or 0),
            "total_pages": int(total_pages or 0),
            "start_page": int(start_page or 1),
            "end_page": int(end_page or 0),
            "reverse": reverse,
            "has_more": has_more,
            "timestamp": timestamp or ""
        }
        self._checkpoint_cache[cache_key] = result
        return result

    def start_download(self, provider_id="topcv", mode="moi", options=None):
        options = options or {}
        accounts = self._cfg.accounts_for_source(provider_id)
        selected_account_ids = set(options.get("account_ids") or [])
        if not selected_account_ids and not options.get("scheduled"):
            return {"ok": False, "error": "Hãy chọn một tài khoản trong Danh sách tài khoản vận hành."}
        provider_selected_ids = {account.get("id") for account in accounts
                                 if account.get("id") in selected_account_ids}
        if selected_account_ids:
            accounts = [account for account in accounts
                        if account.get("id") in provider_selected_ids]
        if not accounts:
            return {"ok": False, "error": "Không có tài khoản phù hợp đang bật cho kênh này."}
        runtime_configs = [self._cfg.for_account(account) for account in accounts]
        target = self._provider_browser_target(provider_id, runtime_configs[0] if runtime_configs else self._cfg)
        if not target:
            return {"ok": False, "error": "Nguồn tuyển dụng không hợp lệ."}
        open_profiles = []
        for account, runtime_cfg in zip(accounts, runtime_configs):
            profile = self._provider_browser_target(provider_id, runtime_cfg)[0]()
            if profile_browser_processes(profile):
                open_profiles.append((account, profile))
        if open_profiles:
            if not options.get("confirm_close_profile"):
                return {
                    "ok": False,
                    "requires_profile_close": True,
                    "error": (f"Có {len(open_profiles)} Chrome profile tài khoản đang mở. "
                              "Cần đóng cửa sổ đó trước khi đồng bộ CV."),
                }
            try:
                for account, profile in open_profiles:
                    close_profile_browser(profile)
                    self.log(f"Đã đóng profile {provider_id} · {account.get('email')} theo xác nhận.")
            except ChromeStartError as exc:
                return {"ok": False, "error": str(exc)}
        if mode == "resume":
            # Khung Nâng cao đã nạp checkpoint trước khi bật nút Tiếp tục. Chỉ dùng
            # snapshot đó tại đây; tuyệt đối không đọc SQLite trong đường bấm tải.
            if len(accounts) != 1:
                return {"ok": False, "error": "Chế độ tiếp tục checkpoint chỉ áp dụng cho một tài khoản."}
            cache_key = f"{provider_id}:{accounts[0].get('id')}"
            cp = dict(self._checkpoint_cache.get(cache_key) or {})
            if not cp:
                return {"ok": False, "retryable": True,
                        "error": "Checkpoint chưa tải xong. Vui lòng đợi trạng thái trang được hiển thị rồi thử lại."}
            if not cp.get("has_more") or cp.get("next_page", 0) < 1:
                return {"ok": False, "error": "Không còn checkpoint đang dở để tiếp tục."}
            if cp.get("reverse"):
                options = {
                    "start_page": cp.get("start_page", 1),
                    "end_page": cp["next_page"],
                    "reverse": True,
                    "account_ids": list(selected_account_ids),
                }
            else:
                options = {
                    "start_page": cp["next_page"],
                    "end_page": cp.get("end_page") or None,
                    "reverse": False,
                    "account_ids": list(selected_account_ids),
                }
            mode = "custom"
        start_page = int(options.get("start_page", 1))
        end_page = int(options.get("end_page")) if options.get("end_page") else None
        reverse = bool(options.get("reverse", False))

        with self._lock:
            if self._engine_thread and self._engine_thread.is_alive():
                return {"ok": False, "error": "Đang có tiến trình tải chạy dở."}

            # Tải CV ưu tiên cao nhất: tạm dừng parsing/đồng bộ để nhường máy
            # (giữ nguyên hàng đợi) rồi chờ file parsing đang xử lý kết thúc gọn.
            self._coordinator.notify_download_starting()
            if self._parsing.running():
                self.log("Tạm dừng parsing để nhường tài nguyên cho tải CV; "
                         "chờ file hiện tại hoàn tất...")
                for _ in range(240):          # tối đa ~60s: file đang OCR/parse dở có thể mất hơn 30s
                    if not self._parsing.running():
                        break
                    time.sleep(0.25)
                if self._parsing.running():
                    return {"ok": False, "error": "Parsing chưa dừng kịp. Thử lại sau ít giây."}
            self._log_history = []
            self.log(f"Khởi động hàng đợi {provider_id}: {len(accounts)} tài khoản, chế độ '{mode}'...")

            # Đánh dấu quyền sở hữu trước khi tạo worker để các API giao diện mới chỉ
            # dùng snapshot RAM. Không chờ _db_access_lock trên luồng pywebview: nếu
            # Báo cáo/Dữ liệu đang truy vấn lâu, worker nền sẽ đợi và nút vẫn trả lời ngay.
            with self._db_lock:
                self._exclusive_db_owner = True

            def worker_owned():
                res = {"ok": True, "source": provider_id, "new": 0, "failed": 0,
                       "accounts_total": len(accounts), "accounts_done": 0, "results": []}
                for index, (account, runtime_cfg) in enumerate(zip(accounts, runtime_configs), 1):
                    self.log(f"Tài khoản {index}/{len(accounts)}: {account.get('label') or account.get('email')}")
                    self._engine = SyncEngine(runtime_cfg, source=provider_id, log=self.log,
                                              on_progress=self._on_progress,
                                              on_candidate=self._on_candidate)
                    try:
                        result = self._engine.run(
                            mode=mode, start_page=start_page, end_page=end_page, reverse=reverse)
                    except Exception as exc:
                        import traceback
                        self.log(f"LỖI KHỞI TẠO ({type(exc).__name__}): {exc}\n{traceback.format_exc()}")
                        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                  "source": provider_id, "new": 0, "failed": 0}
                    result["account"] = account.get("email")
                    res["results"].append(result)
                    res["accounts_done"] += 1
                    res["new"] += int(result.get("new", 0))
                    res["failed"] += int(result.get("failed", 0))
                    res["ok"] = res["ok"] and bool(result.get("ok"))
                # Engine đã đóng kết nối ghi candidates; lúc này ghi lịch sử log theo
                # một giao dịch duy nhất, không còn tranh khóa làm chậm tải CV.
                with self._db_access_lock:
                    self._exclusive_db_owner = False
                    self._flush_ui(force_persist=True)
                    self._report_cache.clear()
                    self._report_cache_at.clear()
                    self._filter_options_cache = None
                    self._last_download_result = res
                escaped = json.dumps(res)
                self._eval(f"window.app && window.app.onDownloadFinished({escaped});")
                if res.get("ok") and res.get("new", 0) > 0:
                    notify_new_cvs(res["new"], provider_id)

            def worker():
                try:
                    if not self._db_access_lock.acquire(blocking=False):
                        self.log("Đang chờ tác vụ dữ liệu hiện tại hoàn tất để bàn giao CSDL…")
                        self._db_access_lock.acquire()
                    try:
                        with self._db_lock:
                            self._close_db()
                    finally:
                        self._db_access_lock.release()
                    self.log("Đã bàn giao CSDL; bắt đầu kết nối kênh tuyển dụng.")
                    worker_owned()
                finally:
                    with self._db_access_lock:
                        self._exclusive_db_owner = False

            self._engine_thread = threading.Thread(target=worker, daemon=True)
            try:
                self._engine_thread.start()
            except Exception as exc:
                self._engine_thread = None
                with self._db_lock:
                    self._exclusive_db_owner = False
                return {"ok": False, "error": f"Không tạo được tác vụ đồng bộ: {exc}"}
            return {"ok": True}

    def stop_download(self):
        with self._lock:
            if self._engine:
                self._engine.request_stop()
                message = ("Đã nhận yêu cầu dừng. CV chưa bắt đầu sẽ được hủy; "
                           "một số CV đang tải hoặc ghi dở vẫn sẽ hoàn tất để tránh hỏng dữ liệu.")
                self.log(message)
                return {"ok": True, "message": message}
            return {"ok": False, "error": "Không có tiến trình nào đang chạy."}

    @serialized_db_api
    def start_cv_parsing(self, backfill=True, force=False, retry_failed=False, filters=None,
                         skip_failed=False):
        if self.is_downloading():
            return {"ok": False, "error": "Hãy đợi lượt tải CV kết thúc để không tranh tài nguyên."}
        if self._parsing.running():
            return {"ok": False, "error": "Tiến trình parsing đang chạy."}
        filters = filters or {}
        parsing_filters = {
            "source": self._filter_values(filters.get("source")),
            "account": self._filter_values(filters.get("account")),
            "position": self._filter_values(filters.get("position")),
            "apply_source": self._filter_values(filters.get("channel")),
            "date_from": str(filters.get("date_from", "")).strip(),
            "date_to": str(filters.get("date_to", "")).strip(),
        }
        if parsing_filters["date_from"] and parsing_filters["date_to"] \
                and parsing_filters["date_from"] > parsing_filters["date_to"]:
            return {"ok": False, "error": "Ngày bắt đầu không được lớn hơn ngày kết thúc."}
        db = self._db()
        stats = db.document_stats()
        self._data_stats_cache = db.stats()
        self._close_db()
        started = self._parsing.start(
            bool(backfill), bool(force), bool(retry_failed), parsing_filters,
            skip_failed=bool(skip_failed))
        return {"ok": started, "stats": stats}

    def stop_cv_parsing(self):
        # _parsing.stop() đặt cờ "người dùng chủ động tắt" -> điều phối sẽ KHÔNG
        # tự chạy lại parsing cho tới khi người dùng bấm một nút parsing lần nữa.
        self._parsing.stop()
        return {"ok": True, "message": "Đã yêu cầu dừng sau file CV đang xử lý."}

    def get_cv_parsing_events(self, since=0):
        events = self._parsing.events_since(since)
        return {"ok": True, "events": events,
                "last_seq": events[-1]["seq"] if events else int(since or 0)}

    @serialized_db_api
    def get_cv_parsing_status(self):
        # Đồng bộ nhà tuyển dụng và parsing là hai tác vụ độc lập. Khi luồng tải
        # đang sở hữu SQLite trên Google Drive, chỉ trả snapshot parsing trong RAM;
        # tuyệt đối không mở DB hoặc khởi động parsing ngầm từ API trạng thái.
        if ((getattr(self, "_exclusive_db_owner", False) or self.is_downloading())
                and is_cloud_synced_path(self._cfg.db_path)):
            stats = dict(self._parsing.status)
            stats["running"] = bool(self._parsing.running())
            stats["database_busy"] = True
            return self._with_ocr_status(stats)
        if self._parsing.running():
            stats = dict(self._parsing.status)
            stats["running"] = True
        else:
            try:
                stats = self._db().document_stats()
                stats.update(self._parsing.status)
                stats["running"] = False
                self._parsing_stats_cache = stats
            except (sqlite3.OperationalError, Exception):
                stats = dict(getattr(self, "_parsing_stats_cache", None) or self._parsing.status)
                stats["running"] = False
                stats["database_busy"] = True
        return self._with_ocr_status(stats)

    @staticmethod
    def _with_ocr_status(stats):
        try:
            from .cv_parser import _tesseract_settings
            _executable, _env, languages = _tesseract_settings()
            stats["ocr_available"] = True
            stats["ocr_languages"] = languages.split("+")
        except Exception:
            stats["ocr_available"] = False
            stats["ocr_languages"] = []
        stats["legacy_office_available"] = runtime_readiness()["checks"]["legacy_office"]["ok"]
        return stats

    def is_downloading(self):
        with self._lock:
            return bool(self._engine_thread and self._engine_thread.is_alive())

    def get_logs(self):
        return self._log_history

    # ================= DỮ LIỆU & TÌM KIẾM =================
    @serialized_db_api
    def get_stats(self):
        if ((getattr(self, "_exclusive_db_owner", False)
             or self.is_downloading() or self._parsing.running())
                and is_cloud_synced_path(self._cfg.db_path)):
            return {**(self._data_stats_cache or {"total": 0, "done": 0, "failed": 0}),
                    "stale": False, "from_memory": True}
        self._data_stats_cache = self._db().stats()
        return self._data_stats_cache

    @serialized_db_api
    def get_candidate_filter_options(self):
        if ((self.is_downloading() or self._parsing.running())
                and is_cloud_synced_path(self._cfg.db_path)):
            return self._filter_options_cache or {"accounts_by_source": {}, "accounts": [],
                                                   "stale": True}
        rows = self._db().candidate_filter_accounts()
        by_source = {}
        totals = {}
        for row in rows:
            source, account = row["source"] or "", row["account"] or ""
            by_source.setdefault(source, []).append(
                {"value": account, "count": int(row["count"] or 0)})
            totals[account] = totals.get(account, 0) + int(row["count"] or 0)
        result = {"accounts_by_source": by_source,
                  "accounts": [{"value": key, "count": value}
                               for key, value in sorted(totals.items())],
                  "positions": self._db().distinct("position")}
        self._filter_options_cache = result
        return result

    @serialized_db_api
    def get_candidate_parsing(self, source, account, cv_id):
        if (self.is_downloading() or self._parsing.running()) and is_cloud_synced_path(self._cfg.db_path):
            return {"ok": False, "busy": True,
                    "error": "Chi tiết parsing sẽ cập nhật sau khi tác vụ hiện tại hoàn tất."}
        row = self._db().get_document(str(source or ''), str(account or ''), str(cv_id or ''))
        return {"ok": True, "document": row}

    @serialized_db_api
    def get_candidate_detail(self, source, account, cv_id):
        """Đọc lại đúng một bản ghi ứng viên từ CSDL cho modal "Xem chi tiết".

        Bảng danh sách trên UI có thể đang hiển thị snapshot RAM cũ (khi engine
        tải/parsing trên ổ đám mây, get_candidates trả cache "stale"), nên các
        trường chỉ điền được sau khi mở trang chi tiết (nơi làm việc mong muốn,
        tình trạng hôn nhân, ngoại ngữ...) chưa kịp xuất hiện. Đọc lẻ một dòng
        theo khoá định danh thì nhẹ và luôn cho giá trị mới nhất.
        """
        from app.db import _FIELDS
        try:
            row = self._db().get_candidate(
                str(source or ''), str(cv_id or ''),
                str(account or '') or None)
        except Exception as exc:  # ổ đám mây khoá file trong chốc lát
            return {"ok": False, "error": str(exc)[:120]}
        if row is None:
            return {"ok": False, "error": "not_found"}
        keys = row.keys() if hasattr(row, "keys") else _FIELDS
        candidate = {key: (row[key] if row[key] is not None else "")
                     for key in keys}
        return {"ok": True, "candidate": candidate}

    @serialized_db_api
    def get_parsing_documents(self, filters=None):
        filters = filters or {}
        limit = max(10, min(100, int(filters.get("limit", 25))))
        offset = max(0, int(filters.get("offset", 0)))
        parse_status = str(filters.get("parse_status", "")).strip()
        search = str(filters.get("search", "")).strip()
        source = self._filter_values(filters.get("source"))
        account = self._filter_values(filters.get("account"))
        position = str(filters.get("position", "")).strip()
        date_from = str(filters.get("date_from", "")).strip()
        date_to = str(filters.get("date_to", "")).strip()

        # Khi engine tải hoặc parsing đang chạy trên Google Drive, tránh mở connection thứ 2 gây xung đột file DB
        if (self.is_downloading() or self._parsing.running()) and is_cloud_synced_path(self._cfg.db_path):
            cached = getattr(self, '_parsing_doc_cache', None)
            if cached is not None:
                return {**cached, "ok": True, "busy": True}
            return {"ok": True, "items": [], "total": 0, "busy": True,
                    "message": "Danh sách chi tiết sẽ cập nhật sau khi tiến trình bóc tách hiện tại hoàn tất."}

        db = self._db()
        items, total = db.query_parsing_documents(
            limit=limit, offset=offset, parse_status=parse_status, search=search,
            source=source, account=account, position=position,
            date_from=date_from, date_to=date_to)
        res = {"ok": True, "items": items, "total": total}
        self._parsing_doc_cache = res
        return res

    @staticmethod
    def _filter_values(value):
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value or "").strip()
        return [text] if text else []

    @serialized_db_api
    def get_candidates(self, filters=None):
        filters = filters or {}
        # Never return the whole database to the webview. Rendering thousands of
        # rows blocks its UI thread even when SQLite itself answers quickly.
        limit = max(10, min(200, int(filters.get("limit", 100))))
        offset = max(0, int(filters.get("offset", 0)))
        search = str(filters.get("search", "")).strip()
        source = self._filter_values(filters.get("source"))
        account = self._filter_values(filters.get("account"))
        dl_status = str(filters.get("dl_status", "")).strip()
        position = str(filters.get("position", "")).strip()
        date_from = str(filters.get("date_from", "")).strip()
        date_to = str(filters.get("date_to", "")).strip()
        sort_by = str(filters.get("sort_by", "applied_ts")).strip()
        sort_dir = str(filters.get("sort_dir", "DESC")).strip().upper()
        cache_key = (limit, offset, search, tuple(source), tuple(account), dl_status, position,
                     date_from, date_to, sort_by, sort_dir)

        # Khi engine đang sở hữu DB trên Google Drive, tuyệt đối không mở connection
        # thứ hai chỉ để render UI. Trang gần nhất đã đọc đủ cho việc chuyển tab tức thì.
        if (self.is_downloading() or self._parsing.running()) and is_cloud_synced_path(self._cfg.db_path):
            cached = self._candidate_cache.get(cache_key)
            if cached is None and not any((search, source, account, dl_status, position,
                                           date_from, date_to)):
                cached = next(iter(self._candidate_cache.values()), None)
            if cached is not None:
                return {**cached, "stale": True}
            return {"items": [], "total": 0, "stale": True,
                    "message": "Dữ liệu sẽ được cập nhật sau khi lượt đồng bộ hoàn tất."}

        if sort_dir not in ["ASC", "DESC"]:
            sort_dir = "DESC"

        from app.db import _FIELDS
        if sort_by not in _FIELDS:
            sort_by = "applied_ts"

        order = f"{sort_by} {sort_dir}"

        db = self._db()
        list_columns = tuple(dict.fromkeys(
            key for key, _label in EXPORT_COLUMNS if key != "alerts"))
        rows, total = db.query(
            limit=limit,
            offset=offset,
            order=order,
            columns=list_columns,
            search=search,
            source=source,
            account=account,
            dl_status=dl_status,
            position=position,
            date_from=date_from,
            date_to=date_to
        )
        breakdown = db.candidate_filter_breakdown(
            search=search, source=source, account=account, dl_status=dl_status,
            position=position, date_from=date_from, date_to=date_to)
        items = [{key: (r[key] if r[key] is not None else "") for key in list_columns}
                 for r in rows]
        parsing = db.get_document_summaries(
            (item.get("source"), item.get("account"), item.get("cv_id")) for item in items)
        for item in items:
            summary = parsing.get((item.get("source"), str(item.get("account") or '').lower(),
                                   str(item.get("cv_id"))), {})
            item["parse_status"] = summary.get("parse_status", "not_queued")
            item["parse_method"] = summary.get("extraction_method", "")
            item["parse_file_format"] = summary.get("file_format", "")
            item["parse_version"] = summary.get("parser_version", "")
            item["parse_text_length"] = summary.get("text_length", 0)
            item["parse_quality"] = summary.get("quality_score", 0)
            item["parse_needs_ocr"] = summary.get("needs_ocr", 0)
            item["parse_attempts"] = summary.get("attempts", 0)
            item["parse_at"] = summary.get("parsed_at", "")
            item["parse_error"] = summary.get("parse_error", "")
            fields = summary.get("fields") or {}
            item["parse_emails"] = ", ".join(fields.get("emails") or [])
            item["parse_phones"] = ", ".join(fields.get("phones") or [])
            item["parse_urls"] = ", ".join(fields.get("urls") or [])
        alerts = db.candidate_alerts(items)
        for item in items:
            warning = alerts.get((item.get("source"), item.get("account"), item.get("cv_id")), {})
            item["alerts"] = warning.get("detail", "")
            item["alerts_short"] = warning.get("short", "")
            item["applications"] = warning.get("applications", [])
        result = {"items": items, "total": total, "stale": False, **breakdown}
        self._candidate_cache[cache_key] = result
        if len(self._candidate_cache) > 12:
            self._candidate_cache.pop(next(iter(self._candidate_cache)))
        return result

    @serialized_db_api
    def get_report(self, filters=None):
        """Số liệu tổng quan cho tab Báo cáo: KPI, top vị trí ứng tuyển, xu hướng 30 ngày."""
        filters = filters or {}
        cache_key = json.dumps(filters, sort_keys=True, ensure_ascii=False)
        if self.is_downloading() or self._parsing.running():
            cached = self._report_cache.get(cache_key)
            if cached is not None:
                return {**cached, "stale": True,
                        "message": "Đang hiển thị báo cáo gần nhất trong lúc đồng bộ."}
            # Tiến trình tải sở hữu kết nối SQLite duy nhất, nhưng snapshot RAM
            # vẫn đủ cho KPI cơ bản mà không gây tranh chấp cơ sở dữ liệu.
            snapshot = dict(getattr(self, "_data_stats_cache", None) or {})
            total = int(snapshot.get("total") or 0)
            done = int(snapshot.get("done") or 0)
            failed = int(snapshot.get("failed") or 0)
            return {"busy": True, "partial": bool(snapshot),
                    "total": total, "done": done, "failed": failed,
                    "success_rate": round(done * 100 / total, 1) if total else 0,
                    "message": "Đang đồng bộ CV. Các KPI cơ bản được cập nhật realtime; "
                               "báo cáo chi tiết sẽ tự hoàn thiện khi lượt tải kết thúc."}
        cached = self._report_cache.get(cache_key)
        if cached is not None and time.time() - self._report_cache_at.get(cache_key, 0) < 30:
            return {**cached, "cached": True}
        source = self._filter_values(filters.get("source"))
        account = self._filter_values(filters.get("account"))
        position = self._filter_values(filters.get("position"))
        channel = str(filters.get("channel", "")).strip()
        time_range = str(filters.get("time_range", "all")).strip() or "all"

        today = datetime.now().date()
        date_from = date_to = ""
        if time_range == "today":
            date_from = date_to = today.isoformat()
        elif time_range in ("7d", "30d", "90d"):
            days = int(time_range[:-1])
            date_from = (today - timedelta(days=days - 1)).isoformat()
            date_to = today.isoformat()
        elif time_range == "this_month":
            date_from = today.replace(day=1).isoformat()
            date_to = today.isoformat()
        elif time_range == "this_year":
            date_from = today.replace(month=1, day=1).isoformat()
            date_to = today.isoformat()
        elif time_range == "custom":
            date_from = str(filters.get("date_from", "")).strip()
            date_to = str(filters.get("date_to", "")).strip()
            try:
                start = datetime.strptime(date_from, "%Y-%m-%d").date()
                end = datetime.strptime(date_to, "%Y-%m-%d").date()
                if start > end:
                    raise ValueError("Ngày bắt đầu lớn hơn ngày kết thúc.")
            except ValueError as exc:
                raise ValueError(f"Khoảng thời gian báo cáo không hợp lệ: {exc}")
        elif time_range != "all":
            raise ValueError("Bộ lọc thời gian báo cáo không hợp lệ.")

        granularity = "day"
        if date_from and date_to:
            span = (datetime.strptime(date_to, "%Y-%m-%d")
                    - datetime.strptime(date_from, "%Y-%m-%d")).days + 1
            if span > 180:
                granularity = "month"
        elif time_range == "all":
            granularity = "month"

        db = self._db()
        common = dict(source=source, account=account, position=position, apply_source=channel,
                      date_from=date_from, date_to=date_to)
        summary = db.stats_report_summary(**common)
        by_position = db.stats_by_position(**common, limit=8)
        unique_stats = db.stats_unique_candidates(**common)
        by_source_account = db.stats_by_source_account(**common)
        raw_trend_sources = db.stats_by_day_source(**common, granularity=granularity)
        day_totals = {}
        for row in raw_trend_sources:
            day_totals[row["date"]] = day_totals.get(row["date"], 0) + int(row["count"] or 0)
        raw_by_day_rows = [{"date": date, "count": count}
                           for date, count in sorted(day_totals.items())]
        by_day_rows = []
        invalid_date_rows = summary["invalid_dates"]
        date_format = "%Y-%m" if granularity == "month" else "%Y-%m-%d"
        for row in raw_by_day_rows:
            try:
                datetime.strptime(str(row.get("date") or ""), date_format)
                by_day_rows.append(row)
            except (TypeError, ValueError):
                invalid_date_rows += int(row.get("count") or 0)
        if self._filter_options_cache and self._filter_options_cache.get("positions"):
            positions = self._filter_options_cache["positions"]
        else:
            positions = db.distinct("position", source=source)
        channels = []
        by_day_map = {r["date"]: r["count"] for r in by_day_rows}

        by_day = []
        if date_from and date_to and granularity == "day":
            cursor = datetime.strptime(date_from, "%Y-%m-%d").date()
            end = datetime.strptime(date_to, "%Y-%m-%d").date()
            while cursor <= end:
                key = cursor.isoformat()
                by_day.append({"date": key, "count": by_day_map.get(key, 0)})
                cursor += timedelta(days=1)
        elif date_from and date_to and granularity == "month":
            cursor = datetime.strptime(date_from[:7] + "-01", "%Y-%m-%d").date()
            end_key = date_to[:7]
            while cursor.strftime("%Y-%m") <= end_key:
                key = cursor.strftime("%Y-%m")
                by_day.append({"date": key, "count": by_day_map.get(key, 0)})
                cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        elif granularity == "month" and by_day_rows:
            cursor = datetime.strptime(by_day_rows[0]["date"] + "-01", "%Y-%m-%d").date()
            end_key = by_day_rows[-1]["date"]
            while cursor.strftime("%Y-%m") <= end_key:
                key = cursor.strftime("%Y-%m")
                by_day.append({"date": key, "count": by_day_map.get(key, 0)})
                cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            by_day = by_day_rows

        total, done = summary["n"], summary["done"]
        quality = {key: summary[key] for key in
                   ("n", "has_email", "has_phone", "has_file", "has_detail")}
        success_rate = round((done / total) * 100, 1) if total else 0.0
        account_map = {}
        source_map = {}
        for row in by_source_account:
            account_map.setdefault(row["source"], []).append(
                {"account": row["account"], "count": int(row["count"] or 0)})
            aggregate = source_map.setdefault(
                row["source"], {"source": row["source"], "count": 0, "done": 0})
            aggregate["count"] += int(row["count"] or 0)
            aggregate["done"] += int(row.get("done") or 0)
        by_source = sorted(source_map.values(), key=lambda row: row["count"], reverse=True)
        for row in by_source:
            row["accounts"] = account_map.get(row["source"], [])

        def enrich(rows):
            for row in rows:
                count = int(row.get("count") or 0)
                row["share"] = round(count * 100 / total, 1) if total else 0.0
                if "done" in row:
                    row["success_rate"] = round(int(row.get("done") or 0) * 100 / count, 1) if count else 0.0
            return rows

        enrich(by_position)
        enrich(by_source)

        previous_total = None
        change_percent = None
        if date_from and date_to:
            current_start = datetime.strptime(date_from, "%Y-%m-%d").date()
            current_end = datetime.strptime(date_to, "%Y-%m-%d").date()
            span_days = (current_end - current_start).days + 1
            previous_end = current_start - timedelta(days=1)
            previous_start = previous_end - timedelta(days=span_days - 1)
            previous = db.stats_report_summary(
                source=source, account=account, position=position, apply_source=channel,
                date_from=previous_start.isoformat(), date_to=previous_end.isoformat())
            previous_total = previous["n"]
            if previous_total:
                change_percent = round((total - previous_total) * 100 / previous_total, 1)

        periods = len(by_day)
        average_per_period = round(total / periods, 1) if periods else 0.0
        peak = max(by_day, key=lambda row: row["count"], default={"date": "", "count": 0})
        trend_map = {}
        for row in raw_trend_sources:
            trend_map.setdefault(row["date"], {})[row["source"]] = int(row["count"] or 0)
        trend_series = [{"date": row["date"], "total": int(row["count"] or 0),
                         "sources": trend_map.get(row["date"], {})} for row in by_day]
        quality_rates = {
            key: round(int(quality.get(key) or 0) * 100 / total, 1) if total else 0.0
            for key in ("has_email", "has_phone", "has_file", "has_detail")
        }
        parsing = db.stats_parsing(**common)
        result = {
            "total": total, "done": done, "failed": total - done,
            "unique_candidates": unique_stats["unique"],
            "duplicate_applications": max(0, total - unique_stats["unique"]),
            "complete_contact": unique_stats["complete_contact"],
            "success_rate": success_rate,
            "by_position": by_position,
            "by_channel": [],
            "by_source": by_source,
            "by_status": [],
            "by_day": by_day,
            "trend_series": trend_series,
            "quality": quality,
            "quality_rates": quality_rates,
            "parsing": parsing,
            "average_per_period": average_per_period,
            "peak": peak,
            "previous_total": previous_total,
            "change_percent": change_percent,
            "invalid_date_rows": invalid_date_rows,
            "positions": positions,
            "channels": channels,
            "position": position,
            "channel": channel,
            "time_range": time_range,
            "date_from": date_from,
            "date_to": date_to,
            "granularity": granularity,
        }
        self._report_cache[cache_key] = result
        self._report_cache_at[cache_key] = time.time()
        if len(self._report_cache) > 12:
            oldest = next(iter(self._report_cache))
            self._report_cache.pop(oldest)
            self._report_cache_at.pop(oldest, None)
        return result

    def get_cv_data(self, filename):
        """Đọc file CV và trả về nội dung Base64 để xem trực tiếp nội bộ ứng dụng."""
        import base64
        import mimetypes
        if not filename:
            return {"ok": False, "error": "Chưa có tên file CV."}
        path = os.path.join(self._cfg.cv_folder, filename)
        if not os.path.exists(path):
            return {"ok": False, "error": f"Không tìm thấy file: {path}"}
        try:
            mime_type, _ = mimetypes.guess_type(path)
            if not mime_type:
                if filename.lower().endswith(".pdf"):
                    mime_type = "application/pdf"
                elif filename.lower().endswith(".png"):
                    mime_type = "image/png"
                elif filename.lower().endswith((".jpg", ".jpeg")):
                    mime_type = "image/jpeg"
                else:
                    mime_type = "application/octet-stream"

            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")

            return {
                "ok": True,
                "filename": filename,
                "path": path,
                "mime": mime_type,
                "data_url": f"data:{mime_type};base64,{encoded}",
                "ext": os.path.splitext(filename)[1].lower()
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_cv(self, filename):
        if not filename:
            return {"ok": False, "error": "Chưa có tên file CV."}
        path = os.path.join(self._cfg.cv_folder, filename)
        if not os.path.exists(path):
            return {"ok": False, "error": f"Không tìm thấy file: {path}"}
        try:
            os.startfile(path)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_cv_as(self, filename):
        if not filename:
            return {"ok": False, "error": "Chưa có tên file CV."}
        source_path = os.path.abspath(os.path.join(self._cfg.cv_folder, filename))
        cv_root = os.path.abspath(self._cfg.cv_folder)
        if os.path.commonpath([cv_root, source_path]) != cv_root or not os.path.isfile(source_path):
            return {"ok": False, "error": "Không tìm thấy file CV hợp lệ."}
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        target = filedialog.asksaveasfilename(
            initialfile=os.path.basename(filename),
            defaultextension=os.path.splitext(filename)[1],
            filetypes=[("CV file", "*" + os.path.splitext(filename)[1]), ("All files", "*.*")])
        root.destroy()
        if not target:
            return {"ok": False, "cancelled": True}
        try:
            shutil.copy2(source_path, target)
            return {"ok": True, "path": target}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_external_url(self, url):
        """Mở đường dẫn web bên ngoài bằng trình duyệt mặc định hệ thống."""
        import webbrowser
        try:
            webbrowser.open(url)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_folder(self, folder_type="cv"):
        """Mở thư mục lưu CV, CSDL hoặc file nhật ký trên Windows Explorer."""
        try:
            if folder_type == "cv":
                path = os.path.abspath(self._cfg.cv_folder)
            elif folder_type == "db":
                path = os.path.abspath(os.path.dirname(self._cfg.db_path))
            elif folder_type == "log":
                path = os.path.abspath(LOG_PATH)
                if os.path.exists(path):
                    os.startfile(path)
                    return {"ok": True, "path": path}
                path = os.path.abspath(app_dir())
            elif folder_type == "app":
                path = os.path.abspath(app_dir())
            else:
                path = os.path.abspath(app_dir())

            if os.path.exists(path):
                os.startfile(path)
                return {"ok": True, "path": path}
            else:
                return {"ok": False, "error": f"Đường dẫn không tồn tại: {path}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


    # ================= XUẤT BÁO CÁO =================
    @serialized_db_api
    def export_data(self, fmt="xlsx", filters=None):
        filters = filters or {}
        if self.is_downloading() or self._parsing.running():
            return {"ok": False, "error": "Hãy đợi lượt đồng bộ hoàn tất trước khi xuất dữ liệu lớn."}
        selected = filters.get("selected_candidates")
        if not isinstance(selected, list):
            selected = []
        search = str(filters.get("search", "")).strip()
        source = self._filter_values(filters.get("source"))
        account = self._filter_values(filters.get("account"))
        dl_status = str(filters.get("dl_status", "")).strip()
        date_from = str(filters.get("date_from", "")).strip()
        date_to = str(filters.get("date_to", "")).strip()

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        ext = ".xlsx" if fmt == "xlsx" else (".csv" if fmt == "csv" else ".zip")
        filetypes = [("Excel File", "*.xlsx")] if fmt == "xlsx" else ([("CSV File", "*.csv")] if fmt == "csv" else [("ZIP Archive", "*.zip")])
        save_path = filedialog.asksaveasfilename(
            initialdir=self._cfg.export_folder or os.path.expanduser("~"),
            initialfile=f"Bao_cao_ung_vien_{fmt}{ext}",
            defaultextension=ext,
            filetypes=filetypes
        )
        root.destroy()

        if not save_path:
            return {"ok": False, "cancelled": True}

        try:
            db = self._db()
            rows = (db.query_selected(selected) if selected else None)
            if fmt == "zip":
                if rows is None:
                    rows = db.query_all(search=search, source=source, account=account,
                                        dl_status=dl_status, date_from=date_from, date_to=date_to)
                if not rows:
                    return {"ok": False, "error": "Không có dữ liệu phù hợp để xuất."}
                res = export_zip_with_cv(rows, save_path, self._cfg.cv_folder)
                return {"ok": True, "path": save_path, "count": res["included"], "details": res}
            else:
                def export_batches():
                    batches = ([rows] if rows is not None else db.iter_query(
                        batch_size=300,
                        columns=[key for key, _ in EXPORT_COLUMNS if key != "alerts"],
                        search=search, source=source, account=account, dl_status=dl_status,
                        date_from=date_from, date_to=date_to))
                    for batch in batches:
                        values = [dict(row) for row in batch]
                        alerts = db.candidate_alerts(values)
                        for row in values:
                            identity = (row.get("source"), row.get("account"), row.get("cv_id"))
                            row["alerts"] = alerts.get(identity, {}).get("detail", "")
                            yield row
                cnt = export_rows(export_batches(), save_path, fmt=fmt,
                                  cv_folder=self._cfg.cv_folder)
                if not cnt:
                    try:
                        os.remove(save_path)
                    except OSError:
                        pass
                    return {"ok": False, "error": "Không có dữ liệu phù hợp để xuất."}
                return {"ok": True, "path": save_path, "count": cnt}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ================= HẸN GIỜ & THÔNG BÁO =================
    @staticmethod
    def _parse_schedule_start(s):
        """'' -> chạy ngay. 'HH:MM' -> hôm nay (hoặc mai nếu đã qua giờ đó). 'YYYY-MM-DD HH:MM' -> đúng thời điểm đó."""
        now = datetime.now()
        s = (s or "").strip()
        if not s:
            return now
        if len(s) <= 5 and ":" in s:
            hh, mm = s.split(":")
            t = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            return t if t > now else t + timedelta(days=1)
        return datetime.strptime(s, "%Y-%m-%d %H:%M")

    @staticmethod
    def _grid_next_run(anchor, interval_minutes, now):
        """Mốc chạy tiếp theo trên một LƯỚI CỐ ĐỊNH `anchor + k*interval`.

        Cố ý KHÔNG tính từ lúc lượt trước kết thúc (`now + interval`) - làm vậy
        sẽ trôi giờ dần mỗi khi một lượt chạy lâu (vd JobsGO quét toàn bộ hồ
        sơ mất hàng giờ). Nếu lỡ một hoặc nhiều nhịp (lượt trước chạy lâu hơn
        cả interval), nhảy thẳng tới nhịp gần nhất còn ở tương lai - không dồn
        chạy bù liên tiếp nhiều lần."""
        interval = timedelta(minutes=max(15, int(interval_minutes or 60)))
        if anchor > now:
            return anchor
        steps = (now - anchor) // interval + 1
        return anchor + steps * interval

    def _next_schedule_run(self, job_id, job, now=None):
        """Giờ chạy tiếp theo của một lịch: theo lưới cố định, cộng thêm thời
        gian nghỉ giãn cách nếu lịch vừa lỗi liên tiếp (tránh dội liên tục vào
        một tài khoản/site đang lỗi, vd sai mật khẩu, tài khoản bị khoá)."""
        now = now or datetime.now()
        anchor = self._scheduler_job_anchor.get(job_id) or now
        interval = max(15, int(job.get("interval_min") or 60))
        next_at = self._grid_next_run(anchor, interval, now)
        streak = int(job.get("fail_streak") or 0)
        if streak:
            backoff_min = min(SCHEDULE_MAX_BACKOFF_MINUTES, interval * streak)
            next_at = max(next_at, now + timedelta(minutes=backoff_min))
        return next_at

    def _force_recover_stuck_download(self, source):
        """Gọi khi một lượt tải theo lịch đã chạy quá `SCHEDULED_JOB_MAX_MINUTES`
        mà chưa xong - nghi vấn chromedriver/Chrome bị deadlock ở tầng driver
        (không phải timeout trang thông thường, cái đó đã tự ném lỗi sớm hơn
        nhiều). Yêu cầu dừng hợp tác rồi ép đóng Chrome của MỌI tài khoản
        thuộc nguồn này, để lệnh Selenium đang treo gặp lỗi kết nối và luồng
        tải tự thoát. Trả True nếu luồng tải tự kết thúc trong thời gian chờ,
        False nếu vẫn còn sống (không an toàn để lịch tiếp theo chạy)."""
        self.log(f"⚠️ {source}: lượt tải theo lịch treo quá {SCHEDULED_JOB_MAX_MINUTES} phút, "
                 "đang cố khôi phục (yêu cầu dừng + đóng Chrome)...", "WARN")
        try:
            self.stop_download()
        except Exception:                                # noqa: BLE001
            pass
        for account in self._cfg.accounts_for_source(source, enabled_only=False):
            try:
                runtime_cfg = self._cfg.for_account(account)
                target = self._provider_browser_target(source, runtime_cfg)
                if target:
                    close_profile_browser(target[0]())
            except Exception:                            # noqa: BLE001
                pass
        deadline = time.time() + SCHEDULED_JOB_KILL_GRACE_SECONDS
        while time.time() < deadline:
            if not self.is_downloading():
                self.log(f"✓ {source}: đã khôi phục sau khi đóng Chrome; hẹn giờ tiếp tục bình thường.")
                return True
            time.sleep(1)
        return False

    def start_schedule(self):
        """Chạy tuần tự các lịch độc lập để không tranh profile hay cơ sở dữ liệu."""
        with self._lock:
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                return {"ok": False, "error": "Hẹn giờ đang bật rồi."}

            jobs = [job for job in self._cfg.schedule_jobs if job.get("enabled", True)]
            if not jobs:
                return {"ok": False, "error": "Chưa có lịch nào đang bật."}
            sources = sorted({source for job in jobs for source in job.get("sources", [])})
            errs = []
            for source in sources:
                if not self._cfg.accounts_for_source(source):
                    errs.append(f"Chưa có tài khoản bật cho {source}.")
            if errs:
                return {"ok": False, "error": "\n".join(errs)}
            try:
                now = datetime.now()
                self._scheduler_job_anchor = {
                    job["id"]: self._parse_schedule_start(job.get("start_time")) for job in jobs}
                self._scheduler_job_next = {
                    job["id"]: max(now, self._scheduler_job_anchor[job["id"]]) for job in jobs}
                first = min(self._scheduler_job_next.values())
            except Exception:
                return {"ok": False, "error": 'Giờ bắt đầu không hợp lệ. Dùng dạng "08:00" hoặc "2026-08-10 08:00".'}

            self._cfg.schedule_enabled = True
            self._cfg.save()
            self._scheduler_stop.clear()
            self._scheduler_next_run = first

            def loop():
                while not self._scheduler_stop.is_set():
                    jobs_by_id = {job.get("id"): job for job in self._cfg.schedule_jobs
                                  if job.get("enabled", True)}
                    self._scheduler_job_next = {key: value for key, value in self._scheduler_job_next.items()
                                                if key in jobs_by_id}
                    self._scheduler_job_anchor = {key: value for key, value in self._scheduler_job_anchor.items()
                                                  if key in jobs_by_id}
                    now = datetime.now()
                    for job_id, job in jobs_by_id.items():
                        if job_id not in self._scheduler_job_next:
                            try:
                                anchor = self._parse_schedule_start(job.get("start_time"))
                            except Exception:
                                anchor = now
                            self._scheduler_job_anchor[job_id] = anchor
                            self._scheduler_job_next[job_id] = max(now, anchor)
                    if not self._scheduler_job_next:
                        self._scheduler_next_run = None
                        self._cfg.schedule_enabled = False
                        self._cfg.save()
                        break
                    self._scheduler_next_run = min(self._scheduler_job_next.values())
                    due_ids = [job_id for job_id, run_at in self._scheduler_job_next.items()
                               if run_at <= now]
                    if (not due_ids or self.is_downloading() or self._parsing.running()
                            or lockfile.check(self._cfg.db_path)):
                        time.sleep(1)
                        continue
                    aborted = False
                    for job_id in due_ids:
                        job = jobs_by_id.get(job_id)
                        if not job or self._scheduler_stop.is_set():
                            continue
                        errors = []
                        self.log(f"⏰ Chạy lịch: {job.get('name', job_id)}.")
                        for source in job.get("sources", []):
                            self._last_download_result = None
                            result = self.start_download(source, job.get("mode", "moi"), {
                                "account_ids": job.get("account_ids", []), "scheduled": True})
                            if not result.get("ok"):
                                errors.append(f"{source}: {result.get('error', 'lỗi')}")
                                continue
                            wait_started = time.time()
                            timed_out = False
                            while self.is_downloading() and not self._scheduler_stop.is_set():
                                if time.time() - wait_started > SCHEDULED_JOB_MAX_MINUTES * 60:
                                    timed_out = True
                                    break
                                time.sleep(0.5)
                            if timed_out:
                                if self._force_recover_stuck_download(source):
                                    errors.append(
                                        f"{source}: treo quá {SCHEDULED_JOB_MAX_MINUTES} phút, "
                                        "đã tự đóng Chrome và bỏ qua lượt này.")
                                else:
                                    errors.append(
                                        f"{source}: treo quá {SCHEDULED_JOB_MAX_MINUTES} phút và "
                                        "KHÔNG tự khôi phục được.")
                                    self.log(
                                        "⛔ Hẹn giờ đã tự TẮT vì một lượt tải bị treo và không thể "
                                        "khôi phục an toàn. Hãy khởi động lại phần mềm rồi bật lại "
                                        "hẹn giờ.", "ERROR")
                                    self._cfg.schedule_enabled = False
                                    aborted = True
                                    break
                                continue
                            completed = self._last_download_result or {}
                            if not completed.get("ok", True) or completed.get("failed", 0):
                                errors.append(f"{source}: {completed.get('failed', 0)} lỗi")
                        job["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        job["last_status"] = "Hoàn tất" if not errors else "; ".join(errors)
                        job["fail_streak"] = 0 if not errors else int(job.get("fail_streak") or 0) + 1
                        self._cfg.save()
                        if not aborted:
                            self._scheduler_job_next[job_id] = self._next_schedule_run(job_id, job)
                        if aborted:
                            break
                    if aborted:
                        self._scheduler_stop.set()
                        self._scheduler_next_run = None
                        break
                    self._scheduler_next_run = min(self._scheduler_job_next.values())
                    next_str = self._scheduler_next_run.strftime("%Y-%m-%d %H:%M:%S")
                    self._eval(f"window.app && window.app.onScheduleNextRun({json.dumps(next_str)});")

            self._scheduler_thread = threading.Thread(target=loop, daemon=True)
            self._scheduler_thread.start()
            self.log(f"Đã bật {len(jobs)} lịch tự động; các tác vụ sẽ chạy tuần tự.")
            return {"ok": True, "next_run_at": first.strftime("%Y-%m-%d %H:%M:%S")}

    # ---------------- Đồng bộ lên Hub ----------------
    #
    # Đây là cầu nối duy nhất giữa giao diện và `app/sync/`. Mọi phương thức đều
    # trả dict và không bao giờ ném lỗi lên JS: một ngoại lệ vượt qua biên
    # PyWebView sẽ làm nút bấm im lặng không phản hồi, và người dùng không có
    # cách nào biết chuyện gì vừa xảy ra.

    def get_sync_status(self):
        return self._sync.status()

    def test_hub_connection(self):
        return self._sync.test_connection()

    def register_edge_with_hub(self):
        return self._sync.register()

    def sync_now(self, full=False):
        """Đồng bộ ngay một lượt (nút thủ công). `full=True` quét lại toàn bộ kho.
        Ngoài nút này, `PipelineCoordinator` tự chạy đồng bộ khi có CV mới đã parse."""
        return self._sync.run_pass(full=bool(full))

    def retry_failed_sync(self):
        return self._sync.retry_failed()

    def save_hub_config(self, hub_config):
        """Lưu địa chỉ Hub và API key.

        API key đi qua kho bí mật DPAPI như mọi mật khẩu khác, KHÔNG nằm trong
        `cauhinh.json` — cùng lý do với mật khẩu tài khoản nhà cung cấp. Không còn
        chu kỳ đồng bộ: điều phối tự chạy theo delta.
        """
        config = dict(hub_config or {})
        url = str(config.get("hub_url") or "").strip()
        if url and not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "Địa chỉ Hub phải bắt đầu bằng http:// hoặc https://"}

        self._cfg.hub_url = url
        if "hub_api_key" in config:
            self._cfg.set_hub_api_key(config.get("hub_api_key") or "")
        self._cfg.save()
        self.log("Đã lưu cấu hình Hub.")
        return {"ok": True, "status": self._sync.status()}

    def stop_schedule(self):
        with self._lock:
            self._scheduler_stop.set()
            self._scheduler_next_run = None
            self._scheduler_job_next = {}
            self._scheduler_job_anchor = {}
            self._cfg.schedule_enabled = False
            self._cfg.save()
        self.log("Đã tắt hẹn giờ.")
        return {"ok": True}

    def get_schedule_status(self):
        running = bool(self._scheduler_thread and self._scheduler_thread.is_alive()
                        and not self._scheduler_stop.is_set())
        jobs = []
        resolved_scopes = {}
        for job in self._cfg.schedule_jobs:
            account_ids = set(job.get("account_ids") or [])
            accounts = [row for row in self._cfg.provider_accounts
                        if row.get("source") in job.get("sources", [])
                        and row.get("enabled", True)
                        and (not account_ids or row.get("id") in account_ids)]
            issues = []
            for source in job.get("sources", []):
                if not any(row.get("source") == source for row in accounts):
                    issues.append(f"{source}: chưa có tài khoản")
            next_at = self._scheduler_job_next.get(job.get("id")) if running else None
            resolved_scopes[job.get("id")] = {row.get("id") for row in accounts}
            jobs.append({**job, "account_count": len(accounts), "issues": issues,
                         "next_run_at": next_at.strftime("%Y-%m-%d %H:%M:%S") if next_at else None})
        for index, job in enumerate(jobs):
            if not job.get("enabled", True):
                continue
            for other in jobs[:index]:
                if (other.get("enabled", True)
                        and resolved_scopes.get(job.get("id"), set())
                        & resolved_scopes.get(other.get("id"), set())
                        and set(job.get("sources", [])) & set(other.get("sources", []))):
                    job["issues"].append(f"trùng phạm vi với “{other.get('name')}”; hệ thống sẽ xếp hàng")
        return {
            "running": running,
            "sources": self._cfg.schedule_sources or [self._cfg.schedule_source],
            "account_count": sum(len(self._cfg.accounts_for_source(source)) for source in
                                 (self._cfg.schedule_sources or [self._cfg.schedule_source])),
            "next_run_at": (self._scheduler_next_run.strftime("%Y-%m-%d %H:%M:%S")
                             if running and self._scheduler_next_run else None),
            "jobs": jobs,
            "enabled_count": sum(1 for job in jobs if job.get("enabled", True)),
        }

    def maybe_autostart_schedule(self):
        """Gọi 1 lần lúc mở giao diện - tự bật hẹn giờ nếu người dùng đã chọn
        'Tự động bật hẹn giờ khi mở phần mềm' ở lần lưu cấu hình trước đó."""
        if self._cfg.autostart_schedule and self._cfg.schedule_enabled:
            return self.start_schedule()
        return {"ok": False}

    def test_notification(self):
        try:
            ok = notify("MSB Radar Edge",
                        "Thông báo thử nghiệm đã hoạt động. Bạn sẽ nhận thông báo khi có CV mới.",
                        blocking=True)
            return ({"ok": True} if ok else {
                "ok": False,
                "error": "Windows không cho phép ứng dụng gửi thông báo. Hãy kiểm tra Notifications và Do not disturb."
            })
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_about(self):
        return get_about_markdown()
