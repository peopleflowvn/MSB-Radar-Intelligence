# -*- coding: utf-8 -*-
"""Chạy Answer Engine trong một LUỒNG RIÊNG, tách khỏi kết nối client.

Vì sao: mobile treo tab khi người dùng chuyển app → thân `fetch` stream bị OS
huỷ → client thấy "Mất kết nối khi đang trả lời". Trước đây máy chủ **bỏ dở**
generator khi client rớt (`GeneratorExit`), chỉ lưu phần dang dở.

Nay: một luồng chạy `engine.stream_answer` TỚI HẾT, ghi từng chunk vào hàng đợi;
response stream đọc từ hàng đợi. Client rớt → luồng vẫn chạy hết và gọi
`persist(result)` với bản ĐẦY ĐỦ. Người dùng mở lại tab → gọi
`GET /talent/ask/turn/<client_turn_id>/` lấy câu trả lời đã lưu.

Sổ đăng ký `_INFLIGHT` cho endpoint kia biết "đang chạy" (202) hay "không có"
(404) — phần "đã xong" thì đọc thẳng từ bản đã lưu.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import hashlib
import math

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, connection

from . import engine as engine_mod
from . import run_state

log = logging.getLogger(__name__)

#: Response deadline; Python cannot forcibly cancel a blocked provider thread.
HARD_DEADLINE = 150.0
#: Bao lâu giữ một mục đã xong/đã lỗi trong sổ trước khi dọn.
KEEP_DONE = 120.0

_LOCK = threading.Lock()
#: key = (user_id, client_turn_id) → {"state", "at", "error"}
_INFLIGHT: dict[tuple, dict] = {}
# Slots follow actual worker lifetime, including provider I/O after response timeout.
_ACTIVE: set[tuple] = set()

_SENTINEL = object()


def _key(user, client_turn_id):
    return (getattr(user, "pk", None), str(client_turn_id or ""))


def _shared_key(user, client_turn_id):
    digest = hashlib.sha256(str(client_turn_id or "").encode()).hexdigest()
    return f"answer-run:v1:{getattr(user, 'pk', None)}:{digest}"


def _publish_status(user, client_turn_id, state, *, deadline=None):
    """Best-effort shared status; durable answers remain in AssistantMessage."""
    try:
        cache.set(_shared_key(user, client_turn_id),
                  {"state": state, "deadline": deadline},
                  timeout=math.ceil(HARD_DEADLINE + KEEP_DONE))
    except Exception:
        log.warning("answer.runner: shared status unavailable", exc_info=True)


def _shared_status(user, client_turn_id):
    try:
        row = cache.get(_shared_key(user, client_turn_id))
    except Exception:
        log.warning("answer.runner: shared status read failed", exc_info=True)
        return None
    if not isinstance(row, dict):
        return None
    state = row.get("state")
    if state == "running" and row.get("deadline") and time.time() >= row["deadline"]:
        return "timeout"
    return state if state in ("running", "done", "timeout", "error") else None


def _sweep(now):
    stale = [k for k, v in _INFLIGHT.items()
             if k not in _ACTIVE and v["state"] != "running" and now - v["at"] > KEEP_DONE]
    for k in stale:
        _INFLIGHT.pop(k, None)


def status_of(user, client_turn_id):
    """"running" nếu luồng đang chạy, None nếu không có mục nào."""
    with _LOCK:
        _sweep(time.monotonic())
        row = _INFLIGHT.get(_key(user, client_turn_id))
        local_state = row["state"] if row else None
        if (local_state == "running" and row.get("deadline")
                and time.time() >= row["deadline"]):
            local_state = "timeout"
    known = local_state or _shared_status(user, client_turn_id)
    if known:
        return known
    try:
        return run_state.status(user, client_turn_id)
    except Exception:
        log.warning("answer.runner: durable status unavailable", exc_info=True)
        return None


def _threaded_ok():
    """Luồng nền chỉ an toàn khi CSDL cho nhiều kết nối đồng thời.

    SQLite (test, dev nhỏ) khoá cả bảng khi hai luồng cùng ghi → "database table
    is locked". Production dùng PostgreSQL nên không sao. Có thể tắt hẳn bằng
    `settings.ANSWER_RUNNER_THREADED = False`.
    """
    if not getattr(settings, "ANSWER_RUNNER_THREADED", True):
        return False
    return connection.vendor != "sqlite"


def _inline(question, *, envelope, user, history, persist):
    """Chạy engine ngay trong luồng request — dùng khi luồng nền không an toàn.

    Client rớt (`GeneratorExit`) thì như hành vi cũ: persist phần dang dở.
    """
    result = engine_mod.AnswerResult()
    completed = False
    try:
        for chunk in engine_mod.stream_answer(
                question, envelope=envelope, user=user, history=history):
            if chunk.get("type") == "done":
                result = chunk["result"]
                completed = True
                break
            if chunk.get("type") == "error":
                break
            yield chunk
    except GeneratorExit:
        persist(result, aborted=True)
        raise
    except Exception:
        log.exception("answer.runner: inline engine failed")
    try:
        persist(result, aborted=not completed)
    except Exception:
        log.exception("answer.runner: inline persist failed")
        completed = False
    if completed:
        yield {"type": "done", "result": result}
    else:
        yield {"type": "error", "text": "Lượt trả lời không hoàn tất. Bạn có thể thử lại."}


def stream(question, *, envelope, user, history, client_turn_id, persist):
    """Generator SSE-friendly. `persist(result, aborted=False)` được gọi ĐÚNG một
    lần khi luồng sinh xong (kể cả khi client đã rớt)."""
    if not _threaded_ok():
        yield from _inline(question, envelope=envelope, user=user,
                           history=history, persist=persist)
        return
    key = _key(user, client_turn_id)
    q: queue.Queue = queue.Queue(maxsize=256)
    cancelled = threading.Event()
    finished = threading.Event()
    terminal = {}
    response_deadline = time.monotonic() + HARD_DEADLINE
    rejection = ""
    with _LOCK:
        _sweep(time.monotonic())
        limit = max(1, int(getattr(settings, "ANSWER_RUNNER_MAX_WORKERS", 8)))
        if key in _ACTIVE:
            rejection = "Lượt này vẫn đang xử lý. Vui lòng lấy lại kết quả thay vì gửi lại."
        elif len(_ACTIVE) >= limit:
            rejection = "Hệ thống đang xử lý nhiều lượt. Vui lòng thử lại sau."
        else:
            _ACTIVE.add(key)
            _INFLIGHT[key] = {"state": "running", "at": time.monotonic(), "error": "",
                              "deadline": time.time() + HARD_DEADLINE}
    if rejection:
        yield {"type": "error", "text": rejection}
        return
    try:
        claim_id = run_state.claim(user, client_turn_id, HARD_DEADLINE)
    except Exception:
        log.exception("answer.runner: durable claim failed")
        claim_id = None
    if claim_id is None:
        with _LOCK:
            _ACTIVE.discard(key)
            _INFLIGHT.pop(key, None)
        yield {"type": "error", "text": "Không thể bắt đầu lượt này. Hãy lấy lại kết quả hoặc tạo lượt mới."}
        return
    _publish_status(user, client_turn_id, "running", deadline=time.time() + HARD_DEADLINE)

    def _produce():
        result = engine_mod.AnswerResult()
        state, err, timed_out = "error", "incomplete_stream", False
        try:
            for chunk in engine_mod.stream_answer(
                    question, envelope=envelope, user=user, history=history):
                if cancelled.is_set() or time.monotonic() > response_deadline:
                    log.warning("answer.runner: quá HARD_DEADLINE, dừng nhận luồng sinh")
                    state, err, timed_out = "timeout", "deadline", True
                    break
                if chunk.get("type") == "done":
                    result = chunk["result"]
                    state, err = "done", ""
                    break
                if chunk.get("type") == "error":
                    state, err = "error", "engine"
                    break
                try:
                    q.put(chunk, timeout=5)
                except queue.Full:
                    # Client đọc quá chậm / đã rớt — bỏ chunk hiển thị, VẪN chạy
                    # tiếp để có bản đầy đủ mà lưu.
                    pass
        except Exception:                          # noqa: BLE001
            log.exception("answer.runner: luồng sinh hỏng")
            state, err = "error", "engine"
        finally:
            if cancelled.is_set() or time.monotonic() > response_deadline:
                state, err, timed_out = "timeout", "deadline", True
            try:
                persist(result, aborted=timed_out or state == "error")
            except Exception:                      # noqa: BLE001
                log.exception("answer.runner: persist hỏng")
                state, err = "error", "persist"
            try:
                run_state.finish(claim_id, state)
            except Exception:
                log.exception("answer.runner: durable completion failed")
            with _LOCK:
                _INFLIGHT[key] = {"state": state, "at": time.monotonic(),
                                  "error": err}
            _publish_status(user, client_turn_id, state)
            if state == "done":
                terminal.update(type="done", result=result)
            else:
                terminal.update(type="error", text="Lượt trả lời không hoàn tất. Bạn có thể thử lại.")
            try:
                close_old_connections()           # luồng có kết nối DB riêng
            finally:
                with _LOCK:
                    _ACTIVE.discard(key)
                try:
                    q.put_nowait(_SENTINEL)
                except queue.Full:
                    pass
                finished.set()

    worker = threading.Thread(target=_produce, name=f"answer-{client_turn_id}",
                              daemon=True)
    try:
        worker.start()
    except Exception:
        with _LOCK:
            _ACTIVE.discard(key)
            _INFLIGHT[key] = {"state": "error", "at": time.monotonic(), "error": "worker_start"}
        log.exception("answer.runner: worker start failed")
        try:
            run_state.finish(claim_id, "error")
        except Exception:
            log.exception("answer.runner: durable start failure update failed")
        _publish_status(user, client_turn_id, "error")
        yield {"type": "error", "text": "Không khởi động được lượt trả lời. Bạn có thể thử lại."}
        return

    try:
        while True:
            remaining = response_deadline - time.monotonic()
            if remaining <= 0:
                cancelled.set()
                with _LOCK:
                    _INFLIGHT[key] = {"state": "timeout", "at": time.monotonic(),
                                      "error": "deadline"}
                _publish_status(user, client_turn_id, "timeout")
                yield {"type": "error",
                       "text": "Lượt trả lời vượt quá thời gian cho phép. Bạn có thể thử lại."}
                return
            try:
                item = q.get(timeout=min(1.0, remaining))
            except queue.Empty:
                if finished.is_set():
                    yield terminal
                    return
                continue
            if item is _SENTINEL:
                yield terminal
                return
            yield item
    except GeneratorExit:
        # Client rớt (đổi tab, mất mạng). KHÔNG dừng `worker` — để nó chạy hết
        # và persist. Người dùng mở lại sẽ lấy câu trả lời qua endpoint resume.
        log.info("answer.runner: client rớt, luồng sinh vẫn chạy tiếp")
        raise
