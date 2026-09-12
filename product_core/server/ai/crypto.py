# -*- coding: utf-8 -*-
"""Mã hoá khoá API trước khi ghi xuống CSDL.

Mối đe doạ cụ thể: bản dump PostgreSQL, file sao lưu, hoặc ảnh chụp CSDL lọt ra
ngoài. Lưu khoá dạng rõ nghĩa là mất luôn khoá của cả bốn nhà cung cấp.

Khác với khoá API của Edge — chỗ đó Hub chỉ cần *kiểm tra* nên lưu hash là đủ.
Ở đây Hub phải *dùng lại* khoá để gọi nhà cung cấp, nên bắt buộc là mã hoá hai
chiều chứ không phải hàm băm.

Khoá mã hoá lấy từ MSB_AI_CONFIG_KEY nếu có, không thì dẫn xuất từ SECRET_KEY.

    Hệ quả phải biết: đổi SECRET_KEY mà không đặt MSB_AI_CONFIG_KEY thì các khoá
    đã lưu không giải mã được nữa. Hệ thống KHÔNG sập — nó báo khoá cần nhập lại.
    Đặt MSB_AI_CONFIG_KEY riêng để tách hai vòng đời đó ra.
"""
import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

log = logging.getLogger(__name__)

ENV_KEY = "MSB_AI_CONFIG_KEY"
_SALT = b"msb-radar-ai-provider-config-v1"


class DecryptError(RuntimeError):
    """Không giải mã được — gần như luôn do đổi khoá mã hoá."""


def _fernet():
    raw = os.environ.get(ENV_KEY, "")
    if raw:
        # Cho phép đặt thẳng khoá Fernet 32 byte base64, hoặc một chuỗi bất kỳ
        # để dẫn xuất — người vận hành không nên phải biết Fernet là gì.
        try:
            return Fernet(raw.encode("utf-8"))
        except (ValueError, TypeError):
            material = raw
    else:
        material = settings.SECRET_KEY

    digest = hashlib.pbkdf2_hmac("sha256", str(material).encode("utf-8"), _SALT, 200_000)
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value):
    """Mã hoá một khoá API. Chuỗi rỗng vẫn là chuỗi rỗng, không phải lỗi."""
    text = str(value or "")
    if not text:
        return ""
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token):
    """Giải mã. Ném DecryptError nếu không đọc được."""
    text = str(token or "")
    if not text:
        return ""
    try:
        return _fernet().decrypt(text.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise DecryptError(
            "Không giải mã được khoá API. Nhiều khả năng SECRET_KEY đã đổi mà "
            f"chưa đặt {ENV_KEY}. Hãy nhập lại khoá.") from exc


def mask(value, keep=6):
    """Dạng che để hiển thị. KHÔNG BAO GIỜ trả khoá đầy đủ về trình duyệt."""
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= keep:
        return "•" * len(text)
    return text[:keep] + "•" * min(12, len(text) - keep)
