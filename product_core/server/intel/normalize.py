# -*- coding: utf-8 -*-
"""Chuẩn hoá giá trị thô trước khi so khớp alias (Master Plan §6).

AI giúp hiểu giá trị thô; **code + registry** quyết định mã chuẩn. Hàm ở đây là
phần "code": tất định, không gọi model.
"""
import re
import unicodedata


def _strip_diacritics(text):
    # đ/Đ là ký tự nguyên tử, NFD KHÔNG tách — phải map tay, nếu không "Đại học"
    # (→ "đai hoc") sẽ không khớp alias "dai hoc".
    text = text.replace("đ", "d").replace("Đ", "D")
    nfd = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")


def normalize_value(text, *, fold_diacritics=True):
    """Chuẩn hoá để so khớp: gọn khoảng trắng, bỏ dấu câu rìa, chữ thường.

    `fold_diacritics=True` (mặc định cho địa danh/skill): bỏ dấu tiếng Việt để
    "Hà Nội" == "ha noi". Với tên riêng thì để False.
    """
    value = unicodedata.normalize("NFKC", str(text or "")).strip().casefold()
    if fold_diacritics:
        value = _strip_diacritics(value)
    value = re.sub(r"[^\w\s/+#.-]", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    return value
