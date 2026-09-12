# -*- coding: utf-8 -*-
"""Xét một dòng nhập liệu: có định danh mạnh không, đã có trong hệ thống chưa.

Dùng lại đúng bộ rút định danh và tra cứu Person của `people/resolution.py` để
kết quả "trùng" ở lưới xem trước khớp với cách bàn nhận sẽ phân giải khi commit.
"""
from people.models import Identity
from people.resolution import extract_identities, find_people

from .fields import IDENTITY_KEYS


def row_identities(fields):
    """Các định danh mạnh rút được từ `fields` (email/phone/linkedin/facebook…).

    `fields` dùng khoá payload nên `extract_identities` đọc thẳng được.
    """
    return extract_identities(fields)


def primary_identity(fields):
    """Chuỗi định danh đại diện cho dòng — dùng để suy `entity_key` và khử trùng
    trong cùng một tệp. `""` nếu không có định danh mạnh nào."""
    identities = {kind: value for kind, value, _ in row_identities(fields)}
    for key in IDENTITY_KEYS:
        kind = {
            "email": Identity.KIND_EMAIL,
            "phone": Identity.KIND_PHONE,
            "linkedin": Identity.KIND_LINKEDIN,
        }[key]
        if identities.get(kind):
            return f"{kind}:{identities[kind]}"
    return ""


def match_person(fields):
    """Person đang tồn tại khớp với dòng này, hoặc None.

    Trả về `(person, is_conflict)`: `is_conflict=True` khi các định danh của dòng
    trỏ tới NHIỀU Person khác nhau — commit sẽ tạo `IdentityConflict`, không tự gộp.
    """
    identities = row_identities(fields)
    if not identities:
        return None, False
    matches = find_people(identities)
    if not matches:
        return None, False
    if len(matches) > 1:
        # Trả một Person bất kỳ để hiển thị; cờ conflict là phần quan trọng.
        any_entry = next(iter(matches.values()))
        return any_entry["person"], True
    return next(iter(matches.values()))["person"], False
