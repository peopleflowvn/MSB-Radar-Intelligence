# -*- coding: utf-8 -*-
"""Nhận diện PII trong văn bản người dùng gõ (Master Plan §19, §23.1.3).

Dùng ở đúng một chỗ: **trước khi** gửi câu hỏi ra dịch vụ web bên ngoài
(Google qua Gemini grounding). Câu hỏi có email/điện thoại/số định danh gần
như chắc chắn nói về một cá nhân cụ thể — không được đẩy ra ngoài kho.

Không cố bắt hết (tên riêng thì regex chịu). Mục tiêu là chặn các mẫu định
danh rõ ràng và các câu hỏi rõ ràng "tra cứu một người".
"""
import re

# Các mẫu định danh cứng.
_EMAIL = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", re.IGNORECASE)
# Điện thoại VN: 0xxxxxxxxx / +84xxxxxxxxx, cho phép . - space xen giữa.
_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\d)")
# Chuỗi 9–12 chữ số liền (CCCD/CMND/MST/số tài khoản).
_ID_NUMBER = re.compile(r"(?<!\d)\d{9,12}(?!\d)")
_ID_WORDS = re.compile(
    r"\b(cccd|cmnd|cмnd|căn cước|can cuoc|hộ chiếu|ho chieu|passport|"
    r"mã số thuế|ma so thue|số tài khoản|so tai khoan)\b", re.IGNORECASE)


def scan(text):
    """Trả list nhãn PII tìm thấy (rỗng nếu không có)."""
    if not text:
        return []
    raw = str(text)
    flags = []
    if _EMAIL.search(raw):
        flags.append("email")
    if _PHONE.search(raw):
        flags.append("phone")
    if _ID_WORDS.search(raw):
        flags.append("id_document")
    elif _ID_NUMBER.search(raw):
        flags.append("id_number")
    return flags


def contains_pii(text):
    return bool(scan(text))
