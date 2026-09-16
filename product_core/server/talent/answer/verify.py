# -*- coding: utf-8 -*-
"""Kiểm chứng bài viết của ⑤ cho Talent — khung nằm ở `core/answer/verify.py`.

Bốn phép kiểm (thứ tự · số lượng · có nguồn · đúng nguồn) chỉ đọc `name`,
`person_id`, `sort_by`, `limit` và các số `[n]`, nên chúng đúng y hệt khi đối
tượng là khách hàng tiềm năng thay vì ứng viên. Giữ module này làm tên gọi quen
thuộc trong `talent.answer` (và để chỗ đặt phép kiểm riêng của Talent nếu sau
này có), nhưng KHÔNG chép lại logic: hai bản sao sẽ trôi khỏi nhau, và lỗi tìm
được ở một bên sẽ không tự sửa bên kia.
"""
from core.answer.verify import (   # noqa: F401
    MIN_FOR_ORDER,
    _citation_numbers,
    _occurrences,
    _positions,
    check,
    citation_audit,
    repair_messages,
)
