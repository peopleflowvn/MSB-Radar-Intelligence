# -*- coding: utf-8 -*-
"""Sự kiện tiến trình đẩy ra giao diện. Dùng chung mọi domain.

Người dùng nói rõ: **không cần thấy suy nghĩ, cần thấy các bước đang làm** để đỡ
sốt ruột. Nên luồng ra không phải là token suy luận của model, mà là một danh
sách bước ngắn để giao diện tick dần.

Hợp đồng với client (`AiSearch.tsx` và bản Growth tương ứng):

    {"type": "step", "label": "Tìm trong kho", "state": "active"}
    {"type": "step", "label": "Tìm trong kho", "state": "done"}

Cùng một `label` với `state="done"` đánh dấu bước đó đã xong; một `label` mới với
`state="active"` vừa mở bước mới vừa ngầm đóng bước đang chạy. Nhãn chính là
khoá — nên nhãn phải ổn định trong một lượt, và đổi chữ giữa chừng sẽ tạo ra một
bước mới thay vì tick bước cũ.

**Bước cuối luôn được gửi ở `active` và không bao giờ có chunk đóng riêng** —
chỉ có `done` của cả lượt. Client phải tự đóng mọi bước còn treo khi lượt kết
thúc, nếu không thẻ tiến trình quay mãi sau khi câu trả lời đã xong (người dùng
báo 16/09/2026). Ghi ở đây vì đó là hợp đồng hai phía, không phải chi tiết của
riêng bên nào.
"""
from __future__ import annotations


def step(label, state="active"):
    """Một sự kiện bước. Nhãn ngắn, tiếng Việt, đọc là hiểu đang ở đâu."""
    return {"type": "step", "label": label, "state": state}


def drain(generator):
    """Chạy hết một generator, trả `return`-value của nó (bỏ mọi thứ nó yield).

    Dùng cho đường KHÔNG stream: cùng một dây chuyền viết dưới dạng generator
    phục vụ được cả hai kiểu gọi, nên không có hai bản logic lệch nhau giữa
    "trả lời có stream" và "trả lời một cục".
    """
    try:
        while True:
            next(generator)
    except StopIteration as stop:
        return stop.value
