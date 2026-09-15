# -*- coding: utf-8 -*-
"""Điều phối đồng bộ Edge → Hub: nối `runner` vào ứng dụng đang chạy.

## Vì sao module này tồn tại

`runner` biết cách gửi một lô; `service` biết **khi nào** gửi và báo cáo cho ai.
Việc "khi nào" do `PipelineCoordinator` quyết định theo delta (số CV đã parse
xong vượt số đã đồng bộ) và nhường máy cho tải/parsing — `service` chỉ cung cấp
`run_pass()`, `pause()`, `resume()`, `status()` để điều phối gọi.

## Ba nguyên tắc

**Đồng bộ không bao giờ được làm hỏng việc thu thập.** Mọi lỗi đều bị nuốt và
ghi nhật ký. Người dùng mất kết nối Hub vẫn phải tải CV về được — đó là việc
chính của Edge, đồng bộ chỉ là hệ quả.

**Một lượt đồng bộ tại một thời điểm.** Hai luồng cùng `claim_sync_batch()` sẽ
tranh nhau cùng những hàng đó; hàng đợi có khoá riêng nhưng chạy song song
không nhanh hơn — Hub xử lý tuần tự theo lô — mà chỉ làm nhật ký khó đọc.

**Không có hẹn giờ.** Đồng bộ do `PipelineCoordinator` kích hoạt theo delta: chạy
một lượt ngay khi số CV đã tải và parse xong vượt số đã đồng bộ, và tạm dừng
nhường máy khi đang tải CV hoặc đang parsing. Không còn vòng lặp định kỳ.
"""
import sqlite3
import threading
import time
from datetime import datetime

from . import runner
from .client import HubAuthError, HubClient, HubError
from .identity import edge_id as read_edge_id
from ..db import Database

#: Lô cho phép mỗi lượt. Chặn trên để một lượt đồng bộ không chiếm máy hàng giờ
#: khi hàng đợi có hàng chục nghìn bản ghi.
MAX_BATCHES_PER_RUN = 20

#: Quá thời gian này mà cờ `_running` vẫn bật thì coi lượt trước đã chết (mạng
#: treo, tiến trình bị kill) và tự gỡ - để giao diện không kẹt "đang gửi" mãi.
STALE_RUN_SECONDS = 600


class SyncService:
    """Vòng đời đồng bộ: quét → xếp hàng → gửi → báo cáo.

    Nhận `app` là `WebApi` để dùng lại `_db()`, `log()` và cấu hình — không tự
    mở kết nối CSDL riêng, vì kết nối dùng chung là thứ giữ cho ứng dụng chạy
    nhanh khi CSDL nằm trên ổ đám mây (xem `WebApi._db`).
    """

    _EMPTY_QUEUE = {"pending": 0, "inflight": 0, "synced": 0, "failed": 0, "total": 0}

    def __init__(self, app):
        self._app = app
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pause_event = threading.Event()   # set = đang tạm dừng nhường máy
        self._running = False          # đang có một lượt gửi chạy dở
        self._started_at = 0.0         # mốc bắt đầu lượt hiện tại (để tự gỡ khi treo)
        self._blocked_by_user = False  # người dùng đã chủ động tắt đồng bộ
        self._last = {}                # kết quả lượt gần nhất
        self._last_stats = dict(self._EMPTY_QUEUE)   # bản đếm tốt gần nhất
        self._fail_streak = 0          # số lượt lỗi liên tiếp (cho ngắt mạch)
        self._cooldown_until = 0.0     # trước mốc này thì không thử lượt mới

    # ------------------------------------------------------------- trạng thái

    def status(self):
        """Đủ để giao diện vẽ màn hình, không cần gọi thêm gì."""
        config = self._app._cfg
        stale = False
        try:
            stats = self._read_stats()
            self._last_stats = dict(stats)
        except Exception:                              # noqa: BLE001
            # Đang tải/parsing giữ CSDL độc quyền: trả bản đếm tốt gần nhất kèm
            # cờ `stale`, KHÔNG trả toàn số 0 (bản cũ làm vậy nên nhật ký báo
            # "0 CV" dù CV đã đồng bộ).
            stats = dict(self._last_stats)
            stale = True
        cooldown_left = max(0, int(self._cooldown_until - time.time()))
        return {
            "configured": bool(config.hub_url.strip() and config.hub_api_key()),
            "syncing": self.is_syncing(),
            "blocked_by_user": bool(self._blocked_by_user),
            "paused": bool(self._pause_event.is_set()),
            "stale": stale,
            "cooldown_sec": cooldown_left,
            "fail_streak": int(self._fail_streak),
            "hub_url": config.hub_url,
            "edge_id": read_edge_id(),
            "queue": stats,
            "last_run": self._last,
        }

    def in_cooldown(self):
        """Đang trong khoảng nghỉ sau nhiều lượt lỗi liên tiếp (mạng/Hub chặn)?"""
        return time.time() < self._cooldown_until

    def _open_db(self):
        """Kết nối CSDL RIÊNG, ngắn hạn cho đồng bộ - KHÔNG mượn kết nối giao diện
        (`_app._db()`) vì kết nối đó bị khoá độc quyền khi tải/parsing chạy, và
        bản cũ kẹt ở đó khiến `_running` không bao giờ về False."""
        return Database(self._app._cfg.db_path).open()

    def _read_stats(self):
        """Đếm hàng đợi qua kết nối riêng ngắn hạn - không mượn kết nối giao diện."""
        db = self._open_db()
        try:
            return db.sync_stats()
        finally:
            db.close()

    def is_syncing(self):
        """True chỉ khi thật sự có lượt đang chạy chưa quá hạn. Quá `STALE_RUN_SECONDS`
        thì tự coi lượt đó đã chết để giao diện không kẹt 'đang gửi' vĩnh viễn."""
        if not self._running:
            return False
        if self._started_at and time.time() - self._started_at > STALE_RUN_SECONDS:
            self._running = False
            self._last = {**(self._last or {}),
                          "error": "Lượt trước quá hạn nên đã tự huỷ.",
                          "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            return False
        return True

    # ------------------------------------------------------------ thao tác

    def test_connection(self):
        """Nút Kiểm tra kết nối. Không gửi dữ liệu ứng viên nào."""
        client = self._client()
        if client is None:
            return {"ok": False, "error": "Chưa cấu hình địa chỉ Hub hoặc API key."}
        try:
            client.health()
        except HubAuthError as error:
            return {"ok": False, "error": f"API key bị từ chối: {error}"}
        except HubError as error:
            return {"ok": False, "error": str(error)}
        except Exception as error:                     # noqa: BLE001
            return {"ok": False, "error": f"Không gọi được Hub: {error}"}
        return {"ok": True, "detail": "Hub phản hồi bình thường."}

    def register(self):
        """Khai báo máy này với Hub. Idempotent theo `edge_id`."""
        client = self._client()
        if client is None:
            return {"ok": False, "error": "Chưa cấu hình địa chỉ Hub hoặc API key."}
        import platform

        from ..version import APP_VERSION

        try:
            client.register_edge(hostname=platform.node(), app_version=APP_VERSION)
        except HubError as error:
            return {"ok": False, "error": str(error)}
        except Exception as error:                     # noqa: BLE001
            return {"ok": False, "error": f"Không khai báo được với Hub: {error}"}
        return {"ok": True, "edge_id": read_edge_id()}

    def run_pass(self, full=False, mark_parsed_hwm=None):
        """Chạy đúng một lượt đồng bộ trong luồng nền. Trả ngay, không chờ.

        Là điểm vào duy nhất để gửi dữ liệu: nút "Đồng bộ ngay" của người dùng và
        `PipelineCoordinator` đều gọi hàm này. `full=True` quét lại **toàn bộ**
        kho thay vì phần đầu bảng — dùng cho lần đầu và nút "Đồng bộ lại từ đầu".

        `mark_parsed_hwm` (nếu có): ghi mốc `sync_hwm_parsed` = số này khi lượt
        kết thúc không lỗi — để điều phối biết đã quét hết phần parse xong.
        """
        with self._lock:
            if self.is_syncing():
                return {"ok": False, "error": "Một lượt đồng bộ đang chạy."}
            if self.in_cooldown():
                left = int(self._cooldown_until - time.time())
                return {"ok": False, "cooldown": True,
                        "error": f"Hub đang tạm nghỉ sau {self._fail_streak} lượt lỗi "
                                 f"liên tiếp; thử lại sau ~{left} giây."}
            client = self._client()
            if client is None:
                return {"ok": False,
                        "error": "Chưa cấu hình địa chỉ Hub hoặc API key."}
            self._running = True
            self._started_at = time.time()
            self._pause_event.clear()

        def worker():
            try:
                self._run_once(client, full=full, mark_parsed_hwm=mark_parsed_hwm)
            finally:
                with self._lock:
                    self._running = False
                    self._started_at = 0.0
                self._push_status()

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True}

    #: Tên cũ mà cầu nối giao diện đang gọi.
    sync_now = run_pass

    def pause(self, reason="nhường tài nguyên"):
        """Yêu cầu lượt đang chạy dừng gọn sau lô hiện tại. Hàng đợi giữ nguyên."""
        already = self._pause_event.is_set()
        self._pause_event.set()
        if not already and self._running:
            self._app.log(f"Tạm dừng đồng bộ Hub: {reason}.", source="sync")

    def resume(self):
        self._pause_event.clear()

    def set_blocked_by_user(self, blocked):
        self._blocked_by_user = bool(blocked)

    def retry_failed(self):
        """Xếp lại những bản ghi đã bị đánh dấu thất bại.

        Cần thiết vì `fail_sync(retryable=False)` ghi thẳng `failed` — Hub từ
        chối một lô vì API key vừa bị thu hồi, hay vì một bản ghi hỏng, sẽ để
        lại cả lô ở trạng thái đó. Không có nút này thì dữ liệu kẹt vĩnh viễn
        và người dùng không có cách nào biết, chứ đừng nói sửa.
        """
        db = self._open_db()
        try:
            count = db.requeue_failed_sync()
        except Exception as error:                     # noqa: BLE001
            return {"ok": False, "error": str(error)}
        finally:
            db.close()
        self._app.log(f"Đã xếp lại {count} bản ghi đồng bộ thất bại.")
        return {"ok": True, "requeued": count}

    def shutdown(self):
        """Gọi khi đóng ứng dụng. Không chờ luồng — nó là daemon."""
        self._stop.set()
        self._pause_event.set()

    # ------------------------------------------------------------- nội bộ

    def _client(self):
        config = self._app._cfg
        url = config.hub_url.strip()
        key = config.hub_api_key()
        if not (url and key):
            return None
        from .. import net
        resolved = net.resolve_proxies(config)
        proxies = {"http": None, "https": None} if resolved is net._DIRECT else resolved
        return HubClient(url, api_key=key, edge_id=read_edge_id(),
                         proxies=proxies, verify=net.verify_for(config))

    def _run_once(self, client, full=False, mark_parsed_hwm=None):
        """Một lượt: quét → xếp hàng → gửi. Không bao giờ ném lỗi ra ngoài.

        Mở kết nối CSDL RIÊNG, ngắn hạn - không mượn kết nối giao diện (`_app._db()`)
        vì kết nối đó bị khoá độc quyền khi tải/parsing chạy, và bản cũ kẹt ở đó
        khiến `_running` không bao giờ về False ("đang gửi mãi").
        """
        started = time.time()
        result = {"queued": 0, "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        db = None
        try:
            db = self._open_db()
            try:
                db.recover_sync_queue()
            except sqlite3.Error:
                pass
            cv_folder = self._app._cfg.cv_folder

            # Luôn quét toàn bộ theo trang. Bản cũ gọi scan_candidates() từ
            # rowid=0 ở mỗi lượt và bỏ cursor, nên kho >1000 hàng chỉ 1000 hàng
            # đầu được xét trừ khi người dùng tình cờ bấm full sync. Hash khiến
            # hàng không đổi là no-op, nên full scan không tạo traffic thừa.
            result["queued"] += runner.scan_all_candidates(db)
            result["queued"] += runner.scan_all_documents(db, cv_folder)

            totals = runner.drain(
                db, client, edge_id=read_edge_id(),
                batch_size=self._batch_size(), max_batches=MAX_BATCHES_PER_RUN,
                log=lambda text: self._app.log(str(text), source="sync"),
                cv_folder=cv_folder,
                should_continue=lambda: not self._pause_event.is_set())
            result.update(totals)
            # Hub cần mẫu số phía Edge để phát hiện thiếu hồ sơ/file; heartbeat
            # đơn thuần chỉ chứng minh máy còn sống, không chứng minh dữ liệu đủ.
            try:
                doc_stats = db.document_stats()
                queue_stats = db.sync_stats()
                candidate_total = int(db._read(
                    "SELECT COUNT(*) AS n FROM candidates", operation="đếm đối soát"
                ).fetchone()["n"])
                client.report_data({
                    "candidates": {"total": candidate_total},
                    "documents": doc_stats,
                    "outbox": queue_stats,
                    "db_schema_version": db.get_meta("schema_version", ""),
                })
            except Exception as report_error:          # Hub cũ chưa có endpoint
                self._app.log(f"Chưa gửi được số liệu đối soát: {report_error}",
                              "WARN", source="sync")
            if (mark_parsed_hwm is not None and not totals.get("error")
                    and not self._pause_event.is_set()):
                db.set_meta("sync_hwm_parsed", str(int(mark_parsed_hwm)))
        except Exception as error:                     # noqa: BLE001 — xem docstring lớp
            result["error"] = str(error)[:300]
            self._app.log(f"Đồng bộ gặp lỗi: {error}", "ERROR", source="sync")
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:                      # noqa: BLE001
                    pass

        result["seconds"] = round(time.time() - started, 1)
        self._last = result

        # Ngắt mạch: lỗi liên tiếp -> giãn dần khoảng nghỉ (5, 10, 15... tối đa 30
        # phút) để không đập vào Hub mỗi nhịp điều phối khi mạng/tường lửa đang
        # chặn. Một lượt thành công (hoặc không có việc) là gỡ ngay.
        if result.get("error"):
            self._fail_streak += 1
            self._cooldown_until = time.time() + min(1800, 300 * self._fail_streak)
            result["cooldown_sec"] = int(self._cooldown_until - time.time())
        else:
            self._fail_streak = 0
            self._cooldown_until = 0.0

        if result.get("error"):
            pass
        elif result.get("synced") or result.get("uploaded"):
            self._app.log(
                f"Đồng bộ xong: {result.get('synced', 0)} bản ghi, "
                f"{result.get('uploaded', 0)} file CV.", source="sync")
        elif result.get("queued") == 0 and not result.get("claimed"):
            # Không có gì mới - im lặng thay vì báo "Đồng bộ xong: 0 bản ghi"
            # khiến người dùng tưởng dữ liệu bị mất.
            pass
        if result.get("failed"):
            # Nói rõ có cách sửa. Một dòng báo lỗi không kèm lối thoát chỉ làm
            # người dùng lo mà không làm được gì.
            self._app.log(
                f"{result['failed']} bản ghi không gửi được — dùng nút "
                f"«Thử lại bản ghi lỗi» sau khi xử lý nguyên nhân.",
                "WARN", source="sync")

        self._push_status()
        return result

    def _batch_size(self):
        """Kẹp về khoảng an toàn.

        Hub từ chối lô lớn hơn `EDGE_SYNC_MAX_BATCH` (mặc định 500) bằng 413, và
        413 hiện bị coi là lỗi vĩnh viễn — cả lô sẽ bị đánh dấu thất bại. Người
        dùng sửa `cauhinh.json` thành 1000 sẽ tự khoá mình ra khỏi việc đồng bộ
        mà không hiểu vì sao, nên kẹp ở đây chứ không tin số trong file.
        """
        try:
            size = int(self._app._cfg.hub_batch_size or 50)
        except (TypeError, ValueError):
            size = 50
        return max(1, min(size, 200))

    def _push_status(self):
        """Đẩy trạng thái sang giao diện. Hỏng thì im lặng — nó chỉ là hiển thị."""
        try:
            import json

            self._app._eval(
                "window.app && window.app.onSyncStatus("
                f"{json.dumps(self.status(), ensure_ascii=False)});")
        except Exception:                              # noqa: BLE001
            pass
