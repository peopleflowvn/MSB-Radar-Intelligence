# -*- coding: utf-8 -*-
"""
Bộ máy đồng bộ CV - dùng chung cho mọi nguồn tuyển dụng.

Ba chế độ:
  • "moi"   - Chỉ tải CV MỚI: so tổng số trên nguồn tuyển dụng với tổng đã lưu để biết
              trước có khoảng bao nhiêu CV mới, dừng ngay khi đã tìm đủ (hoặc bỏ qua
              hoàn toàn nếu không có gì mới) thay vì phải quét mù nhiều trang.
              Dùng cho chạy định kỳ hằng giờ.
  • "tatca" - Quét TOÀN BỘ danh sách (lần đầu, hoặc khi muốn rà soát lại).
  • "loi"   - CHỈ thử lại các CV trước đó tải lỗi. Không quét danh sách (đã có sẵn đầy đủ
              thông tin ứng viên từ lần trước trong dữ liệu), chỉ gọi lại đúng các mã CV
              đang ở trạng thái lỗi - nhanh và không phụ thuộc việc CV đó có còn nằm
              trong các trang gần đây hay không.

Đặc điểm:
  - Tải nhiều CV cùng lúc nên nhanh hơn nhiều so với bấm tay từng hồ sơ.
  - Dừng giữa chừng an toàn: dữ liệu ghi thẳng vào SQLite nên không mất.
  - CV lỗi tự động thử lại ở lần chạy sau, không tạo dòng trùng.
"""
import os
import sqlite3
import sys
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, CancelledError, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime

from .db import Database, DONE
from .providers import get_provider, LoginError
from .browser import ChromeStartError
from .config import account_for_source
from . import lockfile


def safe_filename(name, maxlen=90):
    import re
    name = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", str(name or ""))
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:maxlen] or "CV"


@dataclass
class Progress:
    phase: str = ""
    done: int = 0
    total: int = 0
    new: int = 0
    skipped: int = 0
    failed: int = 0
    eta_sec: float = 0.0
    stored_total: int = 0
    stored_done: int = 0
    stored_failed: int = 0


class StopRequested(Exception):
    pass


class _RunDone(Exception):
    """Tín hiệu nội bộ: chế độ 'loi' đã xử lý xong, thoát sớm khỏi nhánh chính của run()."""


class SyncEngine:
    # Chế độ "chỉ CV mới": gặp liên tiếp ngần này CV đã có thì coi như hết CV mới
    STOP_AFTER_KNOWN = 45      # = 3 trang liên tiếp toàn CV cũ

    def __init__(self, cfg, source="topcv", log=print, on_progress=None, on_candidate=None):
        self.cfg = cfg
        self.source = source
        self.account = account_for_source(cfg, source)
        def _safe_log(msg):
            try:
                log(msg)
            except Exception:
                try:
                    sys.stdout.buffer.write((str(msg) + "\n").encode("utf-8", errors="replace"))
                    sys.stdout.buffer.flush()
                except Exception:
                    pass
        self.log = _safe_log
        self.on_progress = on_progress or (lambda p: None)
        self.on_candidate = on_candidate or (lambda item, is_new: None)
        self._stop = threading.Event()
        self.progress = Progress()
        self._lock = threading.Lock()
        self._login_error = None   # mất phiên giữa chừng -> chỉ báo MỘT lần rồi dừng
        self._last_lock_touch = 0.0
        self._db_error = None

    def request_stop(self):
        self._stop.set()

    def _finish_futures(self, futures, db):
        """Hủy việc chưa chạy và chỉ chờ các lượt đang ghi/tải dở kết thúc an toàn."""
        pending = set(futures)
        stop_reported = False
        while pending:
            if self._stop.is_set() and not stop_reported:
                cancelled = sum(1 for future in pending if future.cancel())
                running = sum(1 for future in pending if future.running())
                self.log(
                    f"Đang dừng: đã hủy {cancelled:,} CV chưa bắt đầu; "
                    f"chờ {running:,} CV đang xử lý dở hoàn tất an toàn..."
                )
                stop_reported = True
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                try:
                    future.result()
                except (CancelledError, StopRequested):
                    pass
                except LoginError as exc:
                    self._note_login_error(exc)
                except sqlite3.OperationalError as exc:
                    if db._is_transient_write_error(exc):
                        self._note_db_error(exc)
                    else:
                        self.log(f"  ! Lỗi SQLite: {str(exc)[:110]}")
                except Exception as exc:
                    self.log(f"  ! Lỗi: {str(exc)[:110]}")
                self._emit()

    def _note_login_error(self, e):
        """Mất phiên đăng nhập giữa chừng: báo MỘT lần rồi dừng cả tiến trình.

        Nếu để mỗi luồng tự báo, người dùng sẽ thấy hàng loạt dòng lỗi giống hệt nhau,
        và tệ hơn là các CV còn lại bị đánh dấu "lỗi tải" trong dữ liệu dù thực chất
        chúng chưa hề được thử - lần sau bấm "Thử lại CV lỗi" sẽ chạy lại vô ích.
        """
        if self._login_error is None:
            self._login_error = e
            self.log("LỖI ĐĂNG NHẬP: " + str(e))
        self.request_stop()

    def _check_stop(self):
        if self._stop.is_set():
            raise StopRequested()

    def _note_db_error(self, error):
        """Dừng một lần có kiểm soát khi cloud DB không thể ghi kéo dài."""
        if self._db_error is None:
            self._db_error = error
            self.log("LỖI CƠ SỞ DỮ LIỆU ĐÁM MÂY: Không thể ghi dữ liệu kéo dài; "
                     "đã dừng an toàn tại trang chưa hoàn tất để có thể Tiếp tục sau.")
        self.request_stop()

    def _emit(self):
        try:
            self.on_progress(self.progress)
        except Exception:
            pass

    def _touch_run_lock(self, force=False):
        """Gia hạn khóa liên máy tối đa mỗi phút, không ghi ổ đĩa đám mây mỗi trang."""
        now = time.monotonic()
        if force or now - self._last_lock_touch >= 60:
            lockfile.acquire(self.cfg.db_path)
            self._last_lock_touch = now

    def _save_checkpoint(self, db, *, last_page, next_page, total_pages,
                         start_page, end_page, reverse, has_more):
        """Lưu đủ trạng thái để một lần bấm Tiếp tục khôi phục đúng phạm vi/chiều quét."""
        prefix = self._checkpoint_prefix()
        values = {
            "last_page": last_page,
            "next_page": next_page,
            "total_pages": total_pages,
            "start_page": start_page,
            "end_page": end_page,
            "reverse": 1 if reverse else 0,
            "has_more": 1 if has_more else 0,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            db.set_meta_many({prefix + key: value for key, value in values.items()})
            return True
        except sqlite3.OperationalError as exc:
            if db._is_transient_write_error(exc):
                self.log("  ! Chưa lưu được checkpoint do CSDL đám mây đang bận; "
                         "dữ liệu CV đã ghi vẫn được giữ nguyên.")
                return False
            raise

    def _checkpoint_prefix(self):
        import hashlib
        account_key = hashlib.sha256(self.account.encode("utf-8")).hexdigest()[:12]
        return f"checkpoint_{self.source}_{account_key}_"

    # ---------- đặt tên file ----------
    def _build_filename(self, item, ext):
        mapping = {
            "id": item.get("cv_id"),
            "ten": safe_filename(item.get("fullname") or "CV", 60),
            "vitri": safe_filename(item.get("position") or "", 50),
            "ngay": (item.get("applied_at") or "").replace("/", "-").replace(":", "").replace(" ", "_"),
            "nguon": item.get("source") or "",
        }
        pattern = self.cfg.filename_pattern or "{id}_{ten}"
        try:
            base = pattern.format(**mapping)
        except Exception:
            base = f"{mapping['id']}_{mapping['ten']}"
        return safe_filename(base, 120) + ext

    # ---------- tải 1 CV ----------
    def _mark_stored(self, cv_id, success, existing_ids):
        """Cập nhật KPI kho dữ liệu chính xác sau mỗi lần upsert."""
        with self._lock:
            existed = cv_id in existing_ids
            if not existed:
                existing_ids.add(cv_id)
                self.progress.stored_total += 1
                if success:
                    self.progress.stored_done += 1
                else:
                    self.progress.stored_failed += 1
            elif success:
                # CV đã tồn tại nhưng chưa DONE: chuyển từ lỗi/chưa tải sang đã tải.
                self.progress.stored_done += 1
                self.progress.stored_failed = max(0, self.progress.stored_failed - 1)

    def _process_one(self, provider, db, item, done_ids, existing_ids):
        self._check_stop()
        cv_id = str(item.get("cv_id"))

        def publish(is_new):
            payload = dict(item)
            payload["source"] = self.source
            payload["account"] = self.account
            try:
                self.on_candidate(payload, is_new)
            except Exception:
                pass

        if cv_id in done_ids:
            item["dl_status"] = DONE
            stored = db.get_candidate(self.source, cv_id, self.account)
            item["filename"] = stored["filename"] if stored else None
            if (getattr(provider, "supports_detail_enrichment", False)
                    and stored and not stored["detail_loaded"]):
                try:
                    provider.enrich(item)
                    db.upsert(item)
                except Exception as e:
                    self.log(f"  ! Chưa bổ sung được chi tiết mã {cv_id}: {str(e)[:120]}")
            with self._lock:
                self.progress.skipped += 1
                self.progress.done += 1
            self._emit()
            return

        # File đã nằm sẵn trên đĩa -> ghi nhận, khỏi tải lại
        if self.cfg.skip_existing_file:
            stored = db.get_candidate(self.source, cv_id, self.account)
            old = stored["filename"] if stored else None
            if old and os.path.exists(os.path.join(self.cfg.cv_folder, str(old))):
                item["filename"] = old
                item["dl_status"] = DONE
                if (getattr(provider, "supports_detail_enrichment", False)
                        and not stored["detail_loaded"]):
                    try:
                        provider.enrich(item)
                    except Exception as e:
                        self.log(f"  ! Chưa bổ sung được chi tiết mã {cv_id}: {str(e)[:120]}")
                db.upsert(item)
                was_new = cv_id not in existing_ids
                self._mark_stored(cv_id, True, existing_ids)
                publish(was_new)
                with self._lock:
                    self.progress.skipped += 1
                    self.progress.done += 1
                self._emit()
                return

        # Provider nhận cả item để có thể bổ sung dữ liệu chi tiết ngay trước khi tải
        # (VietnamWorks chỉ trả số điện thoại sau khi mở chi tiết ứng viên).
        data, ext_or_err = provider.download(item)
        if data is None and getattr(provider, "run_mode", "") == "loi":
            first_error = str(ext_or_err or "Không tải được CV")
            try:
                refreshed = provider.refresh_failed_item(item)
            except LoginError:
                raise
            except Exception as exc:
                refreshed = False
                self.log(f"  ! Không làm mới được link mã {cv_id}: {str(exc)[:120]}")
            if refreshed:
                self.log(f"  ↻ Đã tìm lại đúng hồ sơ mã {cv_id}; đang thử link mới.")
                data, ext_or_err = provider.download(item)
                if data is None:
                    ext_or_err = f"{ext_or_err} (link cũ: {first_error})"[:180]
        if data is None:
            item["filename"] = ""
            item["dl_status"] = f"Lỗi: {ext_or_err}"
            db.upsert(item)
            was_new = cv_id not in existing_ids
            self._mark_stored(cv_id, False, existing_ids)
            publish(was_new)
            with self._lock:
                self.progress.failed += 1
                self.progress.done += 1
            self._emit()
            self.log(f"  ✗ {item.get('fullname','')} (mã {cv_id}): {ext_or_err}")
            return

        filename = self._build_filename(item, ext_or_err)
        path = os.path.join(self.cfg.cv_folder, filename)
        reuse_existing = False
        if os.path.exists(path):
            import hashlib
            try:
                existing_digest = hashlib.sha256()
                with open(path, "rb") as existing_file:
                    for block in iter(lambda: existing_file.read(1024 * 1024), b""):
                        existing_digest.update(block)
                reuse_existing = existing_digest.digest() == hashlib.sha256(data).digest()
            except OSError:
                reuse_existing = False
            if not reuse_existing:
                stem, e = os.path.splitext(filename)
                account_tag = hashlib.sha256(self.account.encode("utf-8")).hexdigest()[:8]
                filename = f"{stem}_{account_tag}_{cv_id}{e}"
                path = os.path.join(self.cfg.cv_folder, filename)
                counter = 2
                while os.path.exists(path):
                    filename = f"{stem}_{account_tag}_{cv_id}_{counter}{e}"
                    path = os.path.join(self.cfg.cv_folder, filename)
                    counter += 1
        temp_path = f"{path}.{uuid.uuid4().hex}.part"
        try:
            if not reuse_existing:
                with open(temp_path, "wb") as f:
                    f.write(data)
                    f.flush()
                os.replace(temp_path, path)
        except Exception as e:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            item["filename"] = ""
            item["dl_status"] = f"Lỗi ghi file: {str(e)[:80]}"
            db.upsert(item)
            was_new = cv_id not in existing_ids
            self._mark_stored(cv_id, False, existing_ids)
            publish(was_new)
            with self._lock:
                self.progress.failed += 1
                self.progress.done += 1
            self._emit()
            return

        item["filename"] = filename
        item["dl_status"] = DONE
        db.upsert(item)
        was_new = cv_id not in existing_ids
        self._mark_stored(cv_id, True, existing_ids)
        publish(was_new)
        with self._lock:
            self.progress.new += 1
            self.progress.done += 1
        self._emit()
        self.log(f"  ✓ {item.get('fullname','')} → {filename}")

        item_delay_ms = max(
            int(self.cfg.delay_ms or 0),
            int(getattr(provider, "minimum_item_delay_ms", lambda: 0)()))
        if item_delay_ms:
            time.sleep(provider.jitter_delay(
                item_delay_ms / 1000.0,
                provider.item_jitter_ratio,
            ))

    # ---------- chỉ thử lại CV lỗi ----------
    def _run_retry_failed(self, provider, db, conc):
        """
        Không quét lại danh sách - thông tin đầy đủ của ứng viên đã có sẵn trong dữ liệu
        từ lần trước (kể cả khi lần đó tải lỗi). Chỉ cần thử tải lại đúng file CV cho các
        mã đang ở trạng thái lỗi. Nhanh hơn nhiều so với quét lại vì không phụ thuộc việc
        CV đó có còn nằm trong các trang gần đây trên nguồn tuyển dụng hay không.
        """
        rows = db.query_all(source=self.source, account=self.account, dl_status="failed")
        existing_ids = db.all_ids(self.source, self.account)
        self.log(f"Tìm thấy {len(rows):,} CV lỗi cần thử lại.")
        self.progress.total = len(rows)
        self.progress.phase = f"Đang thử lại {len(rows):,} CV lỗi..."
        self._emit()
        if not rows:
            return

        pool = ThreadPoolExecutor(max_workers=conc)
        futures = []
        try:
            for row in rows:
                self._check_stop()
                futures.append(pool.submit(
                    self._process_one, provider, db, dict(row), set(), existing_ids))
                while len([f for f in futures if not f.done()]) >= conc * 6:
                    futures = [f for f in futures if not f.done()]
                    self._emit()
                    time.sleep(0.15)
                    self._check_stop()

            self.progress.phase = "Đang hoàn tất..."
            self._emit()
            self._finish_futures(futures, db)
        except StopRequested:
            self._finish_futures(futures, db)
            raise
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            db.commit()
            self._touch_run_lock(force=True)

    # ---------- vòng chạy chính ----------
    def run(self, mode="moi", start_page=1, end_page=None, reverse=False):
        t0 = time.time()
        self._stop.clear()
        self.progress = Progress(phase="Đang chuẩn bị...")
        self._emit()

        errs = self.cfg.validate(self.source)
        if errs:
            for e in errs:
                self.log("LỖI CẤU HÌNH: " + e)
            return {"ok": False, "error": "\n".join(errs)}

        os.makedirs(self.cfg.cv_folder, exist_ok=True)

        self.log("Đang mở CSDL và nạp trạng thái kênh…")
        db = Database(self.cfg.db_path, log=self.log).open()
        initial_stats = db.stats(self.source, account=self.account)
        self.progress.stored_total = initial_stats["total"]
        self.progress.stored_done = initial_stats["done"]
        self.progress.stored_failed = initial_stats["failed"]
        self._touch_run_lock(force=True)
        self.log("CSDL đã sẵn sàng. Đang khởi động kết nối trang tuyển dụng…")
        provider = get_provider(self.source, self.cfg, log=self.log)
        provider.run_mode = mode
        stats = {"ok": True, "new": 0, "skipped": 0, "failed": 0, "stopped": False}
        provider_limit = (provider.concurrency_limit()
                          if hasattr(provider, "concurrency_limit")
                          else getattr(provider, "max_concurrency", 8))
        conc = max(1, min(8, int(self.cfg.concurrency), int(provider_limit)))

        try:
            self.progress.phase = f"Đang kết nối {provider.display_name}..."
            self._emit()
            provider.connect()
            if self.source == "vietnamworks" and mode == "tatca":
                self.log(f"Chế độ backup lịch sử an toàn: {conc} luồng tải, "
                         "điều tiết request dùng chung và checkpoint sau từng trang.")

            if mode == "loi":
                self._run_retry_failed(provider, db, conc)
                stats.update({"new": self.progress.new, "skipped": self.progress.skipped,
                             "failed": self.progress.failed})
                raise _RunDone()

            total_cv = provider.total_count()
            last_page = getattr(provider, "last_page", 1)
            db_total_all = db.count(self.source, account=self.account)
            self.log(f"{provider.display_name} hiện có {total_cv:,} lượt ứng tuyển "
                     f"({last_page:,} trang) · dữ liệu đã lưu {db_total_all:,} lượt.")

            done_ids = db.done_ids(self.source, self.account)
            existing_ids = db.all_ids(self.source, self.account)

            # Xác định dải trang
            sp = max(1, int(start_page or 1))
            ep = int(end_page) if end_page else last_page
            if ep > last_page:
                ep = last_page
            if sp > ep:
                raise ValueError(f"Phạm vi trang không hợp lệ: từ trang {sp} lớn hơn trang {ep}.")

            if mode == "custom":
                self.log(f"Chế độ TÙY CHỌN TRANG: Quét từ trang {sp} đến trang {ep}" +
                         (" (TẢI NGƯỢC)" if reverse else ""))
                if hasattr(provider, "range_total"):
                    selected_total = provider.range_total(sp, ep)
                else:
                    page_size = max(1, len(provider.peek_first_page()) or 15)
                    selected_total = (ep - sp + 1) * page_size
                    if ep == last_page:
                        last_count = max(0, total_cv - page_size * (last_page - 1))
                        selected_total -= max(0, page_size - last_count)
                self.progress.total = max(0, selected_total)
            elif mode == "tatca":
                self.progress.total = total_cv

            expected_new = max(0, total_cv - db_total_all)
            skip_scan = False
            if mode == "moi":
                self.log(f"Ước tính có khoảng {expected_new:,} lượt ứng tuyển mới cần tải.")
                if (expected_new == 0
                        and getattr(provider, "safe_first_page_no_change", True)):
                    first_items = provider.peek_first_page()
                    if first_items and all(str(it.get("cv_id")) in done_ids for it in first_items):
                        self.log("Không có CV mới kể từ lần chạy trước. Bỏ qua, không cần quét.")
                        self.progress.done = self.progress.total = len(first_items)
                        self.progress.skipped = len(first_items)
                        skip_scan = True
                    else:
                        self.log("Có thay đổi bất thường trong danh sách, vẫn quét để đảm bảo chính xác.")

            if not skip_scan:
                pool = ThreadPoolExecutor(max_workers=conc)
                consecutive_known = 0
                new_found = 0
                scan_complete = False
                last_processed_page = 0
                scanned_pages = 0

                # Trước khi tải trang đầu tiên, checkpoint trỏ đúng vào trang sắp làm.
                first_page = ep if reverse else sp
                self._save_checkpoint(
                    db, last_page=0, next_page=first_page, total_pages=last_page,
                    start_page=sp, end_page=ep, reverse=reverse, has_more=True)

                try:
                    for page_no, items in provider.iter_pages(start_page=sp, end_page=ep, reverse=reverse):
                        self._check_stop()

                        known_here = sum(1 for it in items if str(it.get("cv_id")) in done_ids)
                        new_found += len(items) - known_here
                        if mode == "moi":
                            consecutive_known = (consecutive_known + known_here
                                                 if known_here == len(items) else 0)
                            self.progress.total += len(items)

                        direction_str = " (Ngược)" if reverse else ""
                        self.progress.phase = f"Trang {page_no:,}/{last_page:,}{direction_str}"
                        self._emit()

                        page_futures = []
                        for it in items:
                            page_futures.append(pool.submit(
                                self._process_one, provider, db, it, done_ids, existing_ids))

                        # Chỉ xác nhận xong trang sau khi TẤT CẢ CV của trang đã kết thúc.
                        # Nếu người dùng bấm Dừng giữa trang, checkpoint vẫn trỏ vào chính
                        # trang đó; lần sau quét lại an toàn và tự bỏ qua CV đã tải xong.
                        self._finish_futures(page_futures, db)

                        db.commit()
                        self._check_stop()

                        last_processed_page = page_no
                        scanned_pages += 1
                        next_page = page_no - 1 if reverse else page_no + 1
                        has_more = sp <= next_page <= ep
                        self._save_checkpoint(
                            db, last_page=page_no, next_page=next_page,
                            total_pages=last_page, start_page=sp, end_page=ep,
                            reverse=reverse, has_more=has_more)
                        self._touch_run_lock()
                        self._update_eta(t0)

                        if (mode == "moi"
                                and not getattr(provider, "scan_all_new_scope", False)):
                            min_pages = max(1, int(getattr(provider, "new_scan_min_pages", 1)))
                            crossed_boundary = known_here == len(items)
                            if (scanned_pages >= min_pages and new_found >= expected_new
                                    and crossed_boundary):
                                self.log(f"Đã tải đủ {new_found:,} CV mới (ước tính {expected_new:,}). Dừng quét.")
                                scan_complete = True
                                break
                            if (scanned_pages >= min_pages
                                    and consecutive_known >= self.STOP_AFTER_KNOWN):
                                self.log("Đã gặp toàn CV cũ - không còn CV mới. Dừng quét.")
                                scan_complete = True
                                break

                        page_delay_ms = max(
                            int(self.cfg.page_delay_ms or 0),
                            int(getattr(provider, "minimum_page_delay_ms", lambda: 0)()))
                        if page_delay_ms:
                            time.sleep(provider.jitter_delay(
                                page_delay_ms / 1000.0,
                                provider.page_jitter_ratio,
                            ))
                    else:
                        scan_complete = True

                    if (scan_complete and mode == "tatca" and sp == 1 and ep == last_page
                            and hasattr(provider, "iter_reconciliation")):
                        self.progress.phase = "Đang đối soát các trang mới nhất..."
                        self._emit()
                        reconciled = 0
                        for check_items in provider.iter_reconciliation():
                            self._check_stop()
                            missing = [it for it in check_items
                                       if str(it.get("cv_id")) not in existing_ids]
                            if not missing:
                                continue
                            self.progress.total += len(missing)
                            check_futures = [pool.submit(
                                self._process_one, provider, db, it, done_ids, existing_ids)
                                for it in missing]
                            for future in check_futures:
                                try:
                                    future.result()
                                except LoginError as e:
                                    self._note_login_error(e)
                                except sqlite3.OperationalError as e:
                                    if db._is_transient_write_error(e):
                                        self._note_db_error(e)
                                    else:
                                        self.log(f"  ! Lỗi SQLite đối soát: {str(e)[:110]}")
                                except Exception as e:
                                    self.log(f"  ! Lỗi đối soát: {str(e)[:110]}")
                            db.commit()
                            reconciled += len(missing)
                        self.log(f"Đối soát cuối lượt hoàn tất: bổ sung {reconciled:,} hồ sơ dịch chuyển/mới phát sinh.")

                    if scan_complete:
                        # Có thể kết thúc sớm ở chế độ "mới", vì vậy phải ghi đúng
                        # trang thực tế vừa hoàn tất thay vì đầu/cuối của cả phạm vi.
                        final_page = last_processed_page or (ep if reverse else sp)
                        final_next = final_page - 1 if reverse else final_page + 1
                        self._save_checkpoint(
                            db, last_page=final_page, next_page=final_next,
                            total_pages=last_page, start_page=sp, end_page=ep,
                            reverse=reverse, has_more=False)

                    self.progress.phase = "Đang hoàn tất..."
                    self._emit()
                finally:
                    # Phải chờ các CV đang tải dở xong rồi mới đóng cơ sở dữ liệu,
                    # nếu không sẽ có file trên đĩa mà không có trong dữ liệu.
                    pool.shutdown(wait=True, cancel_futures=True)

        except _RunDone:
            pass
        except StopRequested:
            stats["stopped"] = True
            self.log("Đã dừng theo yêu cầu. Dữ liệu đã được lưu.")
        except LoginError as e:
            self.log("LỖI ĐĂNG NHẬP: " + str(e))
            stats.update({"ok": False, "error": str(e)})
        except ChromeStartError as e:
            self.log("LỖI TRÌNH DUYỆT: " + str(e))
            stats.update({"ok": False, "error": str(e)})
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.log(f"LỖI KHÔNG XÁC ĐỊNH ({type(e).__name__}): {str(e)}\n{tb}")
            stats.update({"ok": False, "error": f"{type(e).__name__}: {str(e)}"})
        finally:
            try:
                db.commit()
                total_done = db.count(self.source, only_done=True, account=self.account)
            except Exception as exc:
                # Không báo 0 giả sau lượt dài chỉ vì phép đọc tổng cuối cùng bị lock.
                # stored_done đã được tăng ngay sau mỗi upsert thành công; cộng thêm
                # progress.new sẽ đếm đôi toàn bộ CV mới và báo tổng ảo.
                total_done = max(0, int(self.progress.stored_done))
                self.log(f"Không đọc lại được tổng cuối từ SQLite ({exc}); dùng tổng tối thiểu "
                         f"đã xác nhận trong lượt này: {total_done:,}.")
            db.close()
            provider.close()
            lockfile.release(self.cfg.db_path)

        stats.update({
            "new": self.progress.new, "skipped": self.progress.skipped,
            "failed": self.progress.failed, "elapsed": time.time() - t0,
            "total_done": total_done, "source": self.source,
        })
        # Mất phiên giữa chừng thì đây KHÔNG phải một lượt chạy thành công, dù đã kịp
        # tải được một ít - phải báo hỏng để giao diện hiện đúng thông báo cần làm gì.
        if self._login_error is not None:
            stats.update({"ok": False, "error": str(self._login_error)})
        if self._db_error is not None:
            stats.update({"ok": False, "error": str(self._db_error), "stopped": True})
        self.progress.phase = "Hoàn tất"
        self._emit()

        self.log("─" * 46)
        self.log(f"KẾT QUẢ: {stats['new']:,} CV mới tải · {stats['skipped']:,} đã có (bỏ qua) · "
                 f"{stats['failed']:,} lỗi · {self._fmt(stats['elapsed'])}")
        self.log(f"Tổng CV đã lưu ({provider.display_name}): {total_done:,}")
        return stats

    def _update_eta(self, t0):
        p = self.progress
        if p.done > 5 and p.total > p.done:
            rate = p.done / max(0.001, time.time() - t0)
            p.eta_sec = (p.total - p.done) / max(0.001, rate)
        self._emit()

    @staticmethod
    def _fmt(sec):
        sec = int(sec)
        h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
        if h:
            return f"{h} giờ {m} phút"
        if m:
            return f"{m} phút {s} giây"
        return f"{s} giây"
