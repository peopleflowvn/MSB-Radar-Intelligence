# -*- coding: utf-8 -*-
"""Chạy lượt Growth trong luồng riêng — khung nằm ở `core/answer/runner.py`.

Chỉ phần buộc vào Growth. Ngân sách worker dùng CHUNG với Talent: số luồng nền
máy chủ chịu nổi không tự nhân đôi vì có thêm một sản phẩm.
"""
from __future__ import annotations

from core.answer.runner import TurnRunner

from . import engine as engine_mod

# Tra thuộc tính lúc GỌI, không chốt lúc khởi tạo — cùng lý do với
# `talent/answer/runner.py`: chốt sớm thì `mock.patch` lên
# `rb.answer.engine.stream_answer` không có tác dụng, và test resilience xanh
# trong khi chạy engine thật.
_RUNNER = TurnRunner(
    domain="prospect",
    stream_fn=lambda *args, **kwargs: engine_mod.stream_answer(*args, **kwargs),
    result_factory=lambda: engine_mod.AnswerResult(),
)


def status_of(user, client_turn_id):
    return _RUNNER.status_of(user, client_turn_id)


def stream(question, *, envelope, user, history, client_turn_id, persist):
    return _RUNNER.stream(question, envelope=envelope, user=user, history=history,
                          client_turn_id=client_turn_id, persist=persist)
