# -*- coding: utf-8 -*-
"""Vệ sinh câu trả lời trước khi tới người dùng — dùng chung cho mọi nhánh.

Hai lỗi đo được trên production 18–20/09, cả hai đều qua được prompt:

1. **Nhận là đã tìm khi không hề tìm.** Người dùng bấm gợi ý "Nới lỏng tiêu chí
   số năm kinh nghiệm", ① xếp câu đó vào hội thoại chung, và model hội thoại —
   có lịch sử trong tay — viết "Radar đã thực hiện tìm kiếm lại…" kèm bảng 3
   ứng viên. Không có lượt tìm nào chạy. Đây là lỗi tệ nhất có thể: người dùng
   tin một danh sách bịa.
2. **Lộ nhãn nội bộ**: "FACT (Đã xác minh…)", cột "(Inference)", "INFERENCE:".

Nhánh hội thoại KHÔNG có quyền nói về kết quả tìm kiếm của lượt này — nên câu
nhận là đã tìm/lọc ở đây chắc chắn sai, không cần đoán ý.
"""
import re
import unicodedata


def _fold(text):
    value = unicodedata.normalize("NFD", str(text or "").casefold())
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn").replace("đ", "d")


_SEARCH_CLAIM = re.compile(
    r"da (thuc hien )?(tim kiem|tim|loc|ra soat|doc)( lai| sau| them)?\b"
    r"|ket qua (tim kiem|loc)\b|da xac dinh duoc \d+ ung vien"
    r"|ket qua loc tu \d")


def claims_search(text):
    """Câu trả lời có tự nhận vừa tìm/lọc trong kho không."""
    return bool(_SEARCH_CLAIM.search(_fold(text)))


NO_SEARCH_TEXT = (
    "Radar chưa chạy lại tìm kiếm cho yêu cầu này nên không đưa ra danh sách "
    "ứng viên — một danh sách không đi qua bước tìm và đọc hồ sơ thì không đáng "
    "tin. Anh/chị gõ yêu cầu đầy đủ (ví dụ: \"Tìm lại Data Analyst ở Hà Nội, "
    "không bắt buộc 3 năm kinh nghiệm\") để Radar tìm và đọc hồ sơ thật.")

_LABELS = re.compile(
    r"\*{0,2}\b(FACT|INFERENCE|SUGGESTION|UNKNOWN)\b\s*(\([^)]*\))?\s*:?\*{0,2}\s*"
    r"|\s*\((?:Inference|Fact|INFERENCE|FACT)\)")


def strip_internal_labels(text):
    """Bỏ nhãn trạng thái nội bộ khỏi văn bản người dùng đọc."""
    cleaned = _LABELS.sub(lambda m: " " if m.group(0).startswith(" ") else "", str(text or ""))
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()
