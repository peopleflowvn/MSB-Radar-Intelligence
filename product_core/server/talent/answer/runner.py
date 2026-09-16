# -*- coding: utf-8 -*-
"""Chạy lượt Talent trong luồng riêng — khung nằm ở `core/answer/runner.py`.

File này chỉ còn phần buộc vào Talent: chạy `engine.stream_answer` và dựng
`AnswerResult` rỗng khi lượt hỏng trước lúc có gì để lưu. Toàn bộ phần khó —
hạn chót cứng, ngân sách worker dùng chung cả tiến trình, claim một lần trong
CSDL, trạng thái chia sẻ qua cache, hành vi khi client rớt — là hạ tầng và dùng
chung với Growth.

Các hàm cấp module giữ nguyên tên/chữ ký cũ: `answer_views.py` và test gọi qua
chúng.
"""
from __future__ import annotations

from core.answer.runner import (   # noqa: F401 - tên cũ vẫn được import từ đây
    HARD_DEADLINE,
    KEEP_DONE,
    TurnRunner,
    _ACTIVE,
    _INFLIGHT,
    _LOCK,
    _threaded_ok,
)

from . import engine as engine_mod

# Tra cứu thuộc tính lúc GỌI, không chốt hàm lúc khởi tạo. `TurnRunner` giữ
# nguyên thứ nó nhận, nên truyền thẳng `engine_mod.stream_answer` sẽ đóng băng
# đúng đối tượng hàm hiện tại — và `mock.patch("talent.answer.engine.stream_answer")`
# (cách mọi test của runner dựng luồng giả) sẽ thay thuộc tính module mà runner
# không bao giờ đọc lại. Hậu quả không phải test đỏ mà là test XANH trong khi
# chạy engine thật: đúng kiểu hỏng mà một bộ test resilience không được phép có.
_RUNNER = TurnRunner(
    domain="talent",
    stream_fn=lambda *args, **kwargs: engine_mod.stream_answer(*args, **kwargs),
    result_factory=lambda: engine_mod.AnswerResult(),
)


def status_of(user, client_turn_id):
    return _RUNNER.status_of(user, client_turn_id)


def stream(question, *, envelope, user, history, client_turn_id, persist):
    return _RUNNER.stream(question, envelope=envelope, user=user, history=history,
                          client_turn_id=client_turn_id, persist=persist)
