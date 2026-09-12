# -*- coding: utf-8 -*-
"""Parsing bù trên Hub cho CV mà Edge chưa gửi parsed_text."""
import base64
import io
import logging
import re
from pathlib import Path

from ai.router import complete
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from people.models import Document
from people.parsed_text import save_parsed_text
from talent.attachment_text import AttachmentError, extract_file

from .storage import get_storage

log = logging.getLogger(__name__)
TASK = "cv_parsing"
OCR_TASK = "cv_ocr"
SYSTEM_PROMPT = """Bạn là bộ chuẩn hóa văn bản CV. Hãy trả lại đầy đủ nội dung CV dưới dạng
văn bản thuần UTF-8, giữ nguyên dữ kiện, tên riêng, thời gian, chức danh, kỹ năng và thứ tự mục.
Chỉ sửa lỗi ký tự/OCR, khoảng trắng và xuống dòng. Không tóm tắt, không suy diễn, không thêm dữ
kiện và không bọc trong markdown. Chỉ trả văn bản CV."""

#: Ngưỡng để quyết định bản trích cục bộ có đáng đưa qua AI không.
#:
#: Trước đây không có ngưỡng nào: trích cục bộ xong là LUÔN đẩy qua LLM, mọi hồ
#: sơ, không hỏi. Đo trên một CV thật (3.135 ký tự) cho thấy đó là gọi cho có —
#: đầu ra dài 3.130/3.135 ký tự và giữ y nguyên cả 6 năm, 1 email, 8 số. LLM sửa
#: gần như KHÔNG GÌ, đổi lấy 31 giây và một lượt gọi cho mỗi hồ sơ nhập vào.
#:
#: Nên nay chỉ gọi khi bản trích thật sự xấu. Ba dấu hiệu, đều rẻ, đều là thứ bộ
#: trích PDF hỏng theo cách quan sát được:
TY_LE_KHOANG_TRANG_TOI_THIEU = 0.08   # dính chữ: "NguyễnVănAn" thay vì có cách
TY_LE_CHU_TOI_THIEU = 0.55            # rác ký tự: bảng mã hỏng, glyph lỗi
CHUOI_CHU_DAI_NHAT = 45               # cả dòng chữ dính thành một khối

#: Đo chuỗi CHỮ CÁI liền, không phải "từ" dài. Bản đầu đo từ dài và trên 420 CV
#: thật thì một nửa số ca nó bắt là báo động giả: URL LinkedIn 54 ký tự và
#: Facebook 50 ký tự đều là từ dài hoàn toàn hợp lệ. Hai ca còn lại là dấu chấm
#: trang trí (`......` 141 ký tự) và gạch chân kẻ dòng — trang trí xấu chứ chữ
#: không hỏng, mà gọi LLM 31 giây để xoá dấu chấm cũng là gọi cho có.
#:
#: Chuỗi chữ cái thì ba thứ ấy tự loại: URL bị dấu chấm và gạch chéo ngắt (dài
#: nhất còn 8), dấu chấm không có chữ nào, `Expertise____` còn đúng 9. Chỉ chữ
#: thật sự dính liền mới vượt ngưỡng.
_CHUOI_CHU = re.compile(r"[^\W\d_]+", re.UNICODE)


def can_ai_chuan_hoa(text):
    """(có cần không, lý do). Lý do đi vào log để còn chỉnh được ngưỡng.

    Cố ý thiên về BỎ QUA: gọi thừa thì tốn tiền và 30 giây mỗi hồ sơ; bỏ sót thì
    chỉ là text hơi xấu, mà `save_parsed_text` vẫn giữ bản trích cục bộ nên
    không mất gì.
    """
    text = (text or "").strip()
    if len(text) < 200:
        return True, "bản trích quá ngắn, nhiều khả năng hỏng"
    khoang_trang = sum(ch.isspace() for ch in text) / len(text)
    if khoang_trang < TY_LE_KHOANG_TRANG_TOI_THIEU:
        return True, f"thiếu khoảng trắng ({khoang_trang:.1%}), chữ dính nhau"
    chu = sum(ch.isalnum() or ch.isspace() for ch in text) / len(text)
    if chu < TY_LE_CHU_TOI_THIEU:
        return True, f"nhiều ký tự lạ ({1 - chu:.1%}), bảng mã có thể hỏng"
    dai_nhat = max((len(m.group()) for m in _CHUOI_CHU.finditer(text)), default=0)
    if dai_nhat > CHUOI_CHU_DAI_NHAT:
        return True, f"có chuỗi {dai_nhat} chữ cái liền, các từ dính vào nhau"
    return False, ""


def parse_missing_document(document, complete_fn=None):
    """Tự trích và gọi AI khi Document chưa có bất kỳ text nào; lỗi không làm hỏng ingest."""
    document = Document.objects.select_related("primary_text_version").get(pk=document.pk)
    if not document.storage_key:
        return document
    try:
        if document.best_text:
            # Chỉ thử lại AI khi lần trước Hub đã trích được text nhưng provider AI thất bại.
            if document.parse_provider != "hub" or not document.parse_error:
                return document
            extracted = document.best_text
        else:
            data = get_storage().read(document.storage_key)
            upload = SimpleUploadedFile(document.filename or f"cv-{document.pk}.pdf", data,
                                        content_type=document.mime_type or None)
            extracted = extract_file(upload, max_bytes=25 * 1024 * 1024).strip()
            if not extracted:
                extracted, completion = _vision_ocr(document, data, complete_fn=complete_fn)
                save_parsed_text(document, extracted, origin="hub_ai", quality_score=0.9,
                                 provider=completion.provider, model=completion.model)
                return Document.objects.select_related("primary_text_version").get(pk=document.pk)

            # Giữ cả bản parser cục bộ. Nếu AI trả text khác, đó là một phiên bản riêng chứ không ghi đè.
            save_parsed_text(document, extracted, origin="hub_extractor", quality_score=0.55,
                             provider="hub", model="local-extractor")
            can, ly_do = can_ai_chuan_hoa(extracted)
            if not can:
                # Bản trích đã sạch. Gọi LLM ở đây là gọi cho có — đo được là nó
                # trả lại gần đúng nguyên văn, đổi lấy ~30 giây mỗi hồ sơ.
                log.info("Document %s: bỏ qua AI chuẩn hoá, bản trích đủ sạch.",
                         document.pk)
                return Document.objects.select_related("primary_text_version").get(pk=document.pk)
            log.info("Document %s: cần AI chuẩn hoá — %s.", document.pk, ly_do)
        completion = (complete_fn or complete)([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": extracted[:60_000]},
        ], task=TASK, max_tokens=12_000)
        ai_text = _clean_response(completion.text)
        if len(ai_text) < max(20, len(extracted) // 3):
            raise ValueError("AI trả văn bản quá ngắn so với nội dung trích xuất.")
        save_parsed_text(document, ai_text, origin="hub_ai", quality_score=0.85,
                         provider=completion.provider, model=completion.model)
    except Exception as exc:  # noqa: BLE001 - parsing bù không được làm thất bại upload Edge
        log.warning("Hub không parsing bù được Document %s: %s", document.pk, exc)
        document.refresh_from_db()
        if not document.best_text:
            document.parse_status = Document.PARSE_FAILED
        document.parse_error = str(exc)[:500]
        document.parsed_at = timezone.now()
        document.save(update_fields=["parse_status", "parse_error", "parsed_at", "updated_at"])
    return Document.objects.select_related("primary_text_version").get(pk=document.pk)


def _vision_ocr(document, data, complete_fn=None):
    """OCR PDF scan/ảnh qua provider AI vision dùng cùng router và audit log."""
    images = _render_for_ocr(document, data)
    if not images:
        raise AttachmentError("Không tạo được ảnh OCR từ file này.")
    content = [{"type": "text", "text": (
        "Đọc chính xác toàn bộ chữ trong CV scan/ảnh. Trả về văn bản thuần UTF-8, "
        "giữ thứ tự mục, tên riêng, thời gian, chức danh và kỹ năng. Không tóm tắt, "
        "không suy diễn, không dùng markdown.")}]
    content.extend({"type": "image_url", "image_url": {
        "url": f"data:image/jpeg;base64,{base64.b64encode(image).decode('ascii')}",
        "detail": "high"}} for image in images)
    completion = (complete_fn or complete)([
        {"role": "system", "content": "Bạn là OCR chính xác cho hồ sơ ứng viên."},
        {"role": "user", "content": content},
    ], task=OCR_TASK, max_tokens=12_000, reasoning_effort="none")
    text = _clean_response(completion.text)
    if len(text) < 20:
        raise ValueError("AI OCR không trả về đủ văn bản CV.")
    return text, completion


def _render_for_ocr(document, data):
    """Chỉ gửi tối đa 10 trang/ảnh đã nén để có giới hạn chi phí rõ ràng."""
    extension = Path(document.filename or "").suffix.lower()
    if extension == ".pdf" or (document.mime_type or "").lower() == "application/pdf":
        import fitz
        pdf = fitz.open(stream=data, filetype="pdf")
        images = []
        try:
            for page in list(pdf)[:10]:
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                images.append(pix.tobytes("jpeg"))
        finally:
            pdf.close()
        return images
    if (document.mime_type or "").lower() in {"image/jpeg", "image/png", "image/webp"}:
        from PIL import Image
        image = Image.open(io.BytesIO(data)).convert("RGB")
        image.thumbnail((1800, 2400))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=True)
        return [output.getvalue()]
    return []


def _clean_response(value):
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
