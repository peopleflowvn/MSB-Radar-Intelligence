# -*- coding: utf-8 -*-
"""Worker nền của Hub — chỗ AI thực sự chạy khi có dữ liệu mới.

Trước module này, ba việc nặng của Hub đều chỉ tồn tại dưới dạng lệnh gõ tay
(`parse_missing_cvs`, `run_extraction_worker`) và không có cron/systemd nào gọi
chúng. Kết quả đo trên CSDL thật: 1 `ExtractionRun`, 0 `ExtractionJob`, **0
`ExtractedFact` nào có `source_kind="ai"`**. Nói cách khác, tính năng "Hub dùng
AI làm giàu dữ liệu" đã được viết đủ nhưng chưa từng chạy.

Vì sao là một luồng trong tiến trình web chứ không phải Celery/Redis: dự án đã
cố ý chọn "bảng + lệnh" thay vì hàng đợi ngoài (xem `intel/models.py`), và thêm
một hạ tầng nữa chỉ để gọi một hàm mỗi vài giây là cái giá không đáng.

Nhịp làm việc mỗi vòng, theo đúng thứ tự phụ thuộc:
  1. `resolve_pending()`  — bản ghi nguồn → Person (không có Person thì không
     có gì để làm giàu).
  2. parsing bù           — Document có file nhưng chưa có text → trích + AI.
  3. `run_extraction_worker` — Person đã xếp hàng → fact + liên hệ tham chiếu.
"""
import logging
import os
import random
import threading

log = logging.getLogger(__name__)

_thread = None
_stop = threading.Event()

#: Nghỉ giữa hai vòng khi vừa có việc / khi rỗi. Rỗi thì nghỉ dài hơn để không
#: quay CPU và không gõ CSDL liên tục vô ích.
BUSY_SLEEP = 3.0
IDLE_SLEEP = 30.0
#: Số Document parsing bù mỗi vòng. Nhỏ để một vòng không giữ tiến trình quá lâu
#: và để lỗi ở một file không chặn cả hàng.
PARSE_BATCH = 5
EXTRACT_BATCH = 5


def _resolve_pending():
    from people.ingest import resolve_pending
    stats = resolve_pending(limit=200)
    return stats.get("created", 0) + stats.get("matched", 0)


def _parse_documents():
    from people.models import Document

    from .cv_parsing import parse_due_documents
    from .document_preview import prepare_preview

    # Bản xem trước và parse bù là hai hàng đợi RIÊNG. Trước đây chung một truy
    # vấn: file parse lỗi vẫn khớp "chưa có text" nên được chọn lại mỗi 3 giây,
    # mãi mãi, ở cả 3 tiến trình gunicorn — log prod 20/09 lặp đúng 3 file hỏng.
    previews = list(Document.objects.exclude(storage_key="")
                    .filter(preview_status__in=[Document.PARSE_PENDING, ""])
                    .order_by("created_at")[:PARSE_BATCH])
    for document in previews:
        if _stop.is_set():
            break
        try:
            prepare_preview(document)
        except Exception:                        # noqa: BLE001
            log.exception("Worker: không dựng được bản xem trước Document %s", document.pk)
    return len(previews) + parse_due_documents(PARSE_BATCH, stop=_stop)


def _run_extraction():
    from intel.queue import run_worker
    stats = run_worker(batch_size=EXTRACT_BATCH, once=True, worker="hub-background")
    return stats.get("done", 0) + stats.get("failed", 0) + stats.get("requeued", 0)


_STEPS = (("phân giải bản ghi nguồn", _resolve_pending),
          ("parsing bù CV", _parse_documents),
          ("bóc fact + liên hệ", _run_extraction))


def _loop():
    log.info("Worker nền Hub đã khởi động.")
    while not _stop.is_set():
        worked = 0
        for label, step in _STEPS:
            if _stop.is_set():
                break
            try:
                worked += step() or 0
            except Exception:                    # noqa: BLE001
                # Một bước hỏng không được làm chết cả worker: vòng sau thử lại,
                # và hai bước kia vẫn phải chạy.
                log.exception("Worker nền Hub: bước %r lỗi", label)
        base = BUSY_SLEEP if worked else IDLE_SLEEP
        # Jitter để nhiều tiến trình web (gunicorn nhiều worker) không cùng đập
        # vào CSDL một nhịp.
        _stop.wait(base * random.uniform(0.8, 1.3))
    log.info("Worker nền Hub đã dừng.")


#: Tiến trình được phép chạy worker, nhận diện qua argv[0].
_SERVER_PROGRAMS = ("gunicorn", "uvicorn", "daphne", "hypercorn", "waitress")


def should_start():
    """Có nên chạy worker trong tiến trình này không.

    Dùng danh sách CHO PHÉP chứ không phải danh sách chặn. Worker này gọi AI
    thật — tức tiêu tiền và ghi dữ liệu — nên mặc định phải là "không chạy", và
    chỉ bật ở đúng hai nơi ứng dụng thật sự phục vụ: máy chủ WSGI/ASGI, hoặc
    `runserver`. Danh sách chặn thì mỗi lệnh quản trị mới, mỗi script
    `python -c` có `django.setup()` (kể cả script kiểm thử tay) đều âm thầm lọt
    qua và bật một luồng gọi AI mà không ai ngờ.

    `runserver` có autoreload nên sinh hai tiến trình; chỉ tiến trình con
    (`RUN_MAIN=true`) mới là nơi ứng dụng chạy — chạy ở cả hai là gọi AI hai lần.
    """
    import sys

    from django.conf import settings

    if not getattr(settings, "HUB_BACKGROUND_WORKER", False):
        return False
    argv = sys.argv
    program = os.path.basename(argv[0] if argv else "").lower()
    if any(program.startswith(name) for name in _SERVER_PROGRAMS):
        return True
    if len(argv) > 1 and argv[1] == "runserver":
        return os.environ.get("RUN_MAIN") == "true"
    return False


def start():
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="hub-background-worker", daemon=True)
    _thread.start()
    return _thread


def stop(timeout=5.0):
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
