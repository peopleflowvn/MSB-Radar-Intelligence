# -*- coding: utf-8 -*-
"""Bộ điều phối pipeline: Tải CV -> Parsing -> Đồng bộ Hub.

## Vì sao cần module này

Edge có ba tải công việc nền nhưng trước đây không có ai điều phối:

* **Tải CV** chạy khi người dùng bấm hoặc theo lịch hẹn giờ.
* **Parsing** chỉ chạy khi bấm nút - không tự nhận ra có CV mới cần bóc tách.
* **Đồng bộ Hub** chạy theo một vòng lặp hẹn giờ riêng, không biết lúc nào máy
  đang bận tải/parsing nên cứ đâm vào tranh CSDL rồi báo lỗi.

Kết quả: parsing nằm im, đồng bộ báo "0 CV" hoặc kẹt "đang gửi mãi", và cả ba
giành nhau một file SQLite trên ổ đám mây.

## Nguyên tắc

1. **Tuần tự.** Tại một thời điểm chỉ một tầng được đụng CSDL. Ưu tiên:
   Tải CV > Parsing > Đồng bộ Hub.
2. **Phản ứng theo delta, không hẹn giờ.** Parsing tự chạy khi
   `số CV đã tải > số đã parsing`; đồng bộ tự chạy khi
   `số đã parsing (kể cả lỗi) > số đã đồng bộ`.
3. **Nhường máy êm.** Tầng ưu tiên thấp đang chạy mà tầng cao khởi động thì
   *tạm dừng* (giữ nguyên hàng đợi) rồi tự chạy tiếp khi tầng cao xong.
4. **Không bao giờ chết.** Mọi lỗi trong một nhịp đều bị nuốt và ghi nhật ký.
"""
import threading
import time

from .cv_parser import PARSER_VERSION

#: Nhịp kiểm tra. Đủ nhanh để phản ứng, đủ chậm để COUNT trên CSDL đám mây không
#: thành gánh nặng (các truy vấn đều đi qua index sẵn có).
TICK_SECONDS = 10

#: Chờ một chút sau khi mở app: lần đầu CSDL trên Drive có thể đang phục hồi
#: journal / nâng cấp index, đừng chen vào.
STARTUP_GRACE_SECONDS = 15

#: Không khởi động lại parsing dồn dập nếu tồn đọng cứ > 0 vì một lý do bất thường.
PARSING_RESTART_COOLDOWN = 60

_RETRY_MAX_ATTEMPTS = 3
_RETRY_COOLDOWN_HOURS = 6


class PipelineCoordinator:
    def __init__(self, app):
        self._app = app
        self._stop = threading.Event()
        self._thread = None
        self._last_parsing_start = 0.0

    # ------------------------------------------------------------- vòng đời

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="pipeline-coordinator")
        self._thread.start()

    def shutdown(self):
        self._stop.set()

    # ------------------------------------------------------- hook từ web_api

    def notify_download_starting(self):
        """Gọi ngay trước khi luồng tải chiếm CSDL: tạm dừng hai tầng dưới."""
        self._app._parsing.pause("nhường tài nguyên cho tải CV")
        self._app._sync.pause("nhường tài nguyên cho tải CV")

    # --------------------------------------------------------------- nội bộ

    def _active_stage(self):
        if self._app.is_downloading():
            return "download"
        if self._app._parsing.running():
            return "parsing"
        if self._app._sync.is_syncing():
            return "sync"
        return None

    def _loop(self):
        if self._stop.wait(STARTUP_GRACE_SECONDS):
            return
        while not self._stop.wait(TICK_SECONDS):
            try:
                self._tick()
            except Exception as exc:                    # noqa: BLE001
                try:
                    self._app.log(f"Điều phối pipeline gặp lỗi: {exc}", "WARN")
                except Exception:                        # noqa: BLE001
                    pass

    def _tick(self):
        stage = self._active_stage()
        if stage == "download":
            return
        if stage == "parsing":
            # Parsing đang chạy -> đồng bộ phải nhường.
            self._app._sync.pause("nhường tài nguyên cho parsing")
            return
        if stage == "sync":
            return

        # Không có gì chạy: chọn việc theo thứ tự ưu tiên.
        if self._maybe_start_parsing():
            return
        self._maybe_start_sync()

    def _maybe_start_parsing(self):
        parsing = self._app._parsing
        if parsing.running() or not parsing.resume_allowed():
            return False
        if time.time() - self._last_parsing_start < PARSING_RESTART_COOLDOWN:
            return False
        try:
            db = self._app._db()
            requeued = db.requeue_stale_failed_documents(
                _RETRY_MAX_ATTEMPTS, _RETRY_COOLDOWN_HOURS)
            backlog = db.parsing_backlog(PARSER_VERSION)
        except Exception:                                # noqa: BLE001
            return False
        if backlog <= 0 and requeued <= 0:
            return False

        if requeued:
            self._app.log(
                f"Tự động parsing: xếp lại {requeued:,} CV lỗi đã đủ nguội để thử lại.")
        if backlog > 0:
            self._app.log(f"Tự động parsing: phát hiện {backlog:,} CV chưa bóc tách nội dung.")

        self._last_parsing_start = time.time()
        # Đóng kết nối dùng chung để parsing chiếm CSDL độc quyền (giống start_cv_parsing).
        try:
            self._app._close_db()
        except Exception:                                # noqa: BLE001
            pass
        parsing.start(backfill=True, skip_failed=True)
        return True

    def _maybe_start_sync(self):
        sync = self._app._sync
        cfg = self._app._cfg
        if not (cfg.hub_url.strip() and cfg.hub_api_key()):
            return False
        if sync._blocked_by_user or sync.is_syncing() or sync.in_cooldown():
            return False
        sync.resume()
        try:
            db = self._app._db()
            stats = db.sync_stats()
            parsed = db.count_parsed_terminal()
            hwm = int(db.get_meta("sync_hwm_parsed", 0) or 0)
        except Exception:                                # noqa: BLE001
            return False

        pending = int(stats.get("pending", 0)) + int(stats.get("inflight", 0))
        if pending > 0:
            sync.run_pass(full=False)
            return True
        if parsed > hwm:
            # Có CV parse xong mới kể từ lượt đồng bộ sạch gần nhất -> quét lại
            # toàn bộ đúng một lần; `_run_once` sẽ ghi lại mốc khi lượt không lỗi.
            sync.run_pass(full=True, mark_parsed_hwm=parsed)
            return True
        return False
