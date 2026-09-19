# -*- coding: utf-8 -*-
"""Lưu phiên bản text CV, khử trùng theo Person mà không làm mất lịch sử parser."""
import hashlib
import re
import unicodedata

from django.db import transaction
from django.utils import timezone

from .models import DocumentTextLink, ParsedTextVersion


#: Dưới ngưỡng này thì "có text" không có nghĩa là "tìm được". Đo trên prod
#: 20/09: bản trích hỏng dài 64–226 chữ cái — trang bìa TopCV "Ứng viên: X |
#: Nguồn: tuyendung.topcv.vn AID: …" của PDF ảnh, và CV ảnh chỉ trích được dòng
#: liên hệ. CV thật ngắn nhất trong kho có 424 chữ cái.
MIN_USABLE_LETTERS = 300

#: Câu model OCR tự viết khi không thấy chữ. Không được lưu làm nội dung CV: nó
#: lọt vào chỉ mục và làm hồ sơ khớp với truy vấn "văn bản", "hình ảnh"…
_OCR_EMPTY = re.compile(
    r"khong (co|chua|thay|tim thay|doc duoc) (bat ky |mot )?(noi dung |doan )?"
    r"(van ban|chu|ky tu)"
    r"|hinh anh (nay )?(hoan toan )?(trang|trong)"
    r"|trang (hoan toan )?(trang|trong)"
    r"|no (readable |visible )?text|blank (page|image)|does not contain any text")


def _fold(value):
    value = unicodedata.normalize("NFD", str(value or "").casefold())
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn").replace("đ", "d")


def letter_count(text):
    return sum(ch.isalpha() for ch in str(text or ""))


def looks_like_ocr_empty(text):
    """Model OCR trả lời "không có chữ" thay vì trả nội dung."""
    text = str(text or "")
    return letter_count(text) < 600 and bool(_OCR_EMPTY.search(_fold(text)))


def is_usable_text(text):
    """Text đủ để tìm kiếm và để AI đọc — không phải chỉ "khác rỗng"."""
    return letter_count(text) >= MIN_USABLE_LETTERS and not looks_like_ocr_empty(text)


def normalize_text(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


@transaction.atomic
def save_parsed_text(document, text, origin, quality_score=0.0, provider="", model=""):
    normalized = normalize_text(text)
    if not normalized or looks_like_ocr_empty(normalized):
        return None, False
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    version, created = ParsedTextVersion.objects.get_or_create(
        person_id=document.person_id, text_hash=digest,
        defaults={"text": normalized, "text_length": len(normalized)})
    link, _ = DocumentTextLink.objects.get_or_create(
        document=document, text_version=version,
        defaults={"origins": [origin], "provider": provider[:40], "model": model[:100],
                  "quality_score": quality_score})
    changed = []
    origins = list(link.origins or [])
    if origin not in origins:
        origins.append(origin)
        link.origins = origins
        changed.append("origins")
    if quality_score > link.quality_score:
        link.quality_score = quality_score
        link.provider = provider[:40]
        link.model = model[:100]
        changed += ["quality_score", "provider", "model"]
    if changed:
        link.save(update_fields=list(dict.fromkeys(changed)) + ["updated_at"])

    current = document.primary_text_version
    current_quality = document.quality_score if current else -1
    # Bản hiện tại hỏng (trang bìa, câu "không có chữ" của OCR) thì điểm chất
    # lượng của nó vô nghĩa — Edge chấm trang bìa TopCV 0.08 nhưng CV khác có thể
    # bị chấm cao. Bản mới có nhiều chữ hơn thì thay, bất kể điểm.
    current_broken = current is not None and not is_usable_text(current.text)
    should_promote = (current is None or quality_score > current_quality or
                      (quality_score == current_quality and len(normalized) > document.text_length)
                      or (current_broken and letter_count(normalized) > letter_count(current.text)))
    if should_promote:
        document.primary_text_version = version
        document.text_length = len(normalized)
        document.quality_score = quality_score
        document.parse_provider = provider[:40]
        document.parse_model = model[:100]
    document.parsed_text = ""  # trường tương thích cũ; text thật chỉ lưu một lần ở version
    document.parse_status = document.PARSE_DONE
    document.parse_error = ""
    document.parsed_at = timezone.now()
    fields = ["parsed_text", "parse_status", "parse_error", "parsed_at", "updated_at"]
    if should_promote:
        fields += ["primary_text_version", "text_length", "quality_score",
                   "parse_provider", "parse_model"]
    document.save(update_fields=fields)
    return version, created
