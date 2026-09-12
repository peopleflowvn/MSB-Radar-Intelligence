# -*- coding: utf-8 -*-
"""Radar Answer Engine — tầng sinh phản hồi cho câu hỏi về Kho con người.

Thay cho chuỗi cũ `hiring_need.parse → search → scoring → thẻ ứng viên`, vốn ép
mọi câu hỏi vào 11 khoá cố định rồi để một bộ chấm điểm so-chuỗi phủ quyết kết
quả truy hồi (xem `docs/RADAR_ANSWER_ENGINE.md` §1).

Nguyên tắc: **LLM lập kế hoạch và viết; CODE truy hồi, tổng hợp và kiểm chứng.**

    ① plan      QueryPlan linh hoạt (không schema cứng)
    ② retrieve  dense hồ sơ + dense đoạn CV + full-text, đa truy vấn, RRF
    ③ judge     đọc bằng chứng, phán đoán, BÓC thuộc tính câu hỏi cần
    ④ aggregate sắp xếp + cắt theo yêu cầu — tất định, bằng CODE
    ⑤ compose   viết câu trả lời có trích dẫn [n]
"""
from .engine import AnswerResult, answer, stream_answer      # noqa: F401
from .plan import QueryPlan                                  # noqa: F401

# KHÔNG re-export `plan()`/`judge()`/`compose()`: tên hàm trùng tên module con và
# sẽ che mất chính module đó (`answer.plan` hoá ra hàm, không phải module). Muốn
# gọi một chặng riêng thì import thẳng module: `from talent.answer import plan`.
