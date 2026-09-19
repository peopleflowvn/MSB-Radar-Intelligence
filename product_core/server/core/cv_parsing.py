# -*- coding: utf-8 -*-
"""Parsing bù trên Hub cho CV mà Edge chưa gửi text, hoặc gửi text hỏng."""
import base64
import io
import logging
import re
import zipfile
from datetime import timedelta
from pathlib import Path
from xml.etree import ElementTree

from ai.router import complete
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Q
from django.utils import timezone
from people.models import Document
from people.parsed_text import is_usable_text, looks_like_ocr_empty, save_parsed_text
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


class OcrEmpty(ValueError):
    """OCR chạy được nhưng file không có chữ — lỗi CUỐI, thử lại không giúp gì."""


#: Lịch thử lại khi parse bù lỗi (nhà cung cấp AI 429/timeout, file hỏng…).
#: Hết lịch thì chuyển `unreadable` — không gọi OCR mãi cho một file hỏng hẳn —
#: và `parse_missing_cvs --retry-failed` mở lại được bất cứ lúc nào.
RETRY_BACKOFF = (timedelta(minutes=1), timedelta(minutes=10), timedelta(hours=1),
                 timedelta(hours=6), timedelta(hours=24))
#: Giữ chỗ khi một tiến trình đang xử lý. Hub chạy worker trong MỖI tiến trình
#: gunicorn (3 cái): không giữ chỗ thì cùng một file bị OCR ba lần song song.
LEASE = timedelta(minutes=15)
#: Chỉ Document có text ngắn hơn mức này mới cần đọc text ra để kiểm tra chất
#: lượng. Text dài hơn chắc chắn qua `MIN_USABLE_LETTERS`.
CHECK_BELOW_CHARS = 1500


def needs_parsing():
    """Document có file nhưng chưa có text DÙNG ĐƯỢC — hàng đợi của worker.

    Trước đây chỉ bắt "chưa có text nào". Trang bìa TopCV 82 ký tự mà Edge gửi
    lên là "có text", nên 7 CV ảnh nằm im ở trạng thái `done` với nội dung là
    một dòng tên — không tìm được, không ai biết.
    """
    no_text = Q(primary_text_version__isnull=True, parsed_text="")
    # attempts = 0: Hub chưa từng kiểm. attempts > 0 + next_parse_at: lần trước
    # lỗi, đang chờ lượt thử lại. attempts > 0 + không hẹn: Hub đã xác nhận xong.
    unchecked_short = Q(text_length__lt=CHECK_BELOW_CHARS, parse_attempts=0)
    retry_scheduled = Q(parse_attempts__gt=0, next_parse_at__isnull=False)
    return (Document.objects.exclude(storage_key="")
            .exclude(parse_status=Document.PARSE_UNREADABLE)
            .filter(no_text | unchecked_short | retry_scheduled))


def due_for_parsing(now=None):
    now = now or timezone.now()
    return needs_parsing().filter(Q(next_parse_at__isnull=True) | Q(next_parse_at__lte=now))


def claim(document, now=None):
    """Giữ chỗ Document cho tiến trình này. False = tiến trình khác đã giữ."""
    now = now or timezone.now()
    return bool(Document.objects.filter(pk=document.pk)
                .filter(Q(next_parse_at__isnull=True) | Q(next_parse_at__lte=now))
                .update(next_parse_at=now + LEASE))


def parse_due_documents(limit, complete_fn=None, stop=None):
    """Một lượt của worker: nhận và xử lý tối đa `limit` Document đến hạn."""
    handled = 0
    for document in list(due_for_parsing().order_by("next_parse_at", "created_at")[:limit]):
        if stop is not None and stop.is_set():
            break
        if not claim(document):
            continue
        parse_missing_document(document, complete_fn=complete_fn)
        handled += 1
    return handled


def _finish(document, *, error=None, unreadable=False):
    """Ghi kết quả một lượt: thành công, hẹn thử lại, hoặc chốt `unreadable`."""
    document = Document.objects.select_related("primary_text_version").get(pk=document.pk)
    document.parse_attempts = min(document.parse_attempts + 1, 32767)
    document.parsed_at = timezone.now()
    fields = ["parse_attempts", "next_parse_at", "parsed_at", "updated_at"]
    if error is None:
        document.next_parse_at = None
        document.save(update_fields=fields)
        return document
    document.parse_error = str(error)[:500]
    fields += ["parse_error", "parse_status"]
    exhausted = document.parse_attempts > len(RETRY_BACKOFF)
    if exhausted and not unreadable and is_usable_text(document.best_text):
        # Text đã dùng được, chỉ bước AI chuẩn hoá mãi không xong — thôi chuẩn
        # hoá, KHÔNG gắn nhãn "không đọc được" cho một CV tìm được bình thường.
        document.next_parse_at = None
        document.save(update_fields=fields)
        return document
    if unreadable or exhausted:
        document.parse_status = Document.PARSE_UNREADABLE
        document.next_parse_at = None
        # Câu "không có chữ" của OCR đã lỡ lưu làm nội dung CV thì gỡ ra: nó
        # đang nằm trong chỉ mục và khớp bậy với truy vấn.
        if document.primary_text_version_id and looks_like_ocr_empty(document.best_text):
            document.primary_text_version = None
            document.text_length = 0
            fields += ["primary_text_version", "text_length"]
    else:
        if not is_usable_text(document.best_text):
            document.parse_status = Document.PARSE_FAILED
        document.next_parse_at = timezone.now() + RETRY_BACKOFF[document.parse_attempts - 1]
    document.save(update_fields=fields)
    return document


def _text_changed(document, before):
    after = Document.objects.filter(pk=document.pk).values_list(
        "primary_text_version_id", flat=True).first()
    if after and after != before:
        # Text mới ⇒ bóc lại fact (chức danh, kỹ năng…). Chỉ mục và embedding tự
        # theo qua signal `post_save` của Document.
        try:
            from intel.queue import enqueue
            enqueue(document.person_id, batch="reparse")
        except Exception:                          # noqa: BLE001 - intel chưa migrate
            log.exception("Không xếp hàng bóc fact lại cho Person %s", document.person_id)


def parse_missing_document(document, complete_fn=None):
    """Đảm bảo Document có text DÙNG ĐƯỢC; lỗi không làm hỏng ingest.

    Thứ tự: text hiện có đã tốt → xong. Chưa → trích cục bộ (nhận diện định
    dạng theo nội dung file, không tin đuôi) → vẫn chưa tốt → OCR. Lỗi thì hẹn
    thử lại theo `RETRY_BACKOFF`.
    """
    document = Document.objects.select_related("primary_text_version").get(pk=document.pk)
    if not document.storage_key:
        return document
    before = document.primary_text_version_id
    try:
        current = document.best_text or ""
        if is_usable_text(current):
            # Chỉ thử lại AI khi lần trước Hub đã trích được text nhưng provider AI thất bại.
            if document.parse_provider != "hub" or not document.parse_error:
                return _finish(document)
            extracted = current
        else:
            data = get_storage().read(document.storage_key)
            try:
                extracted = extract_document(document, data).strip()
            except Exception as exc:                # noqa: BLE001 - còn OCR phía sau
                log.info("Document %s: trích cục bộ lỗi (%s), chuyển sang AI.", document.pk, exc)
                extracted = ""
            if extracted:
                # Giữ cả bản parser cục bộ. Nếu AI trả text khác, đó là một
                # phiên bản riêng chứ không ghi đè.
                save_parsed_text(document, extracted, origin="hub_extractor",
                                 quality_score=0.55, provider="hub", model="local-extractor")
            if not is_usable_text(extracted):
                # File "cứng đầu": PDF ảnh, CV chụp, Word chỉ chứa ảnh, file
                # hỏng một phần. Cách chắc nhất là cho AI thị giác ĐỌC ẢNH trang.
                ocr_text, completion = _ai_read(document, data, extracted,
                                                complete_fn=complete_fn)
                if ocr_text is not None:
                    # Kết quả ngắn vẫn là nội dung thật của file (CV một trang
                    # ít chữ) nên nhận, không thử lại.
                    save_parsed_text(document, ocr_text, origin="hub_ocr", quality_score=0.9,
                                     provider=completion.provider, model=completion.model)
                    _text_changed(document, before)
                    return _finish(document)
            if not extracted:
                raise AttachmentError("Không trích được chữ và file không OCR được.")
            can, ly_do = can_ai_chuan_hoa(extracted)
            if not can:
                # Bản trích đã sạch. Gọi LLM ở đây là gọi cho có — đo được là nó
                # trả lại gần đúng nguyên văn, đổi lấy ~30 giây mỗi hồ sơ.
                log.info("Document %s: bỏ qua AI chuẩn hoá, bản trích đủ sạch.",
                         document.pk)
                _text_changed(document, before)
                return _finish(document)
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
        _text_changed(document, before)
        return _finish(document)
    except OcrEmpty as exc:
        log.warning("Document %s không có chữ để đọc: %s", document.pk, exc)
        _text_changed(document, before)
        return _finish(document, error=exc, unreadable=True)
    except Exception as exc:  # noqa: BLE001 - parsing bù không được làm thất bại upload Edge
        log.warning("Hub không parsing bù được Document %s: %s", document.pk, exc)
        _text_changed(document, before)
        return _finish(document, error=exc)


# ---------- trích cục bộ: nhận diện định dạng theo NỘI DUNG file ----------

def sniff_extension(data, filename=""):
    """Đuôi thật của file theo nội dung. Đo prod: file .docx thực ra là Excel,
    và file .docx thực ra là zip chứa ảnh chụp CV — tin đuôi thì cả hai hỏng."""
    head = data[:8]
    if head.startswith(b"%PDF"):
        return ".pdf"
    if head.startswith(b"PK"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return Path(filename).suffix.lower()
        if any(n.startswith("word/") for n in names):
            return ".docx"
        if any(n.startswith("xl/") for n in names):
            return ".xlsx"
        if any(n.startswith("ppt/") for n in names):
            return ".pptx"
        if names and all(Path(n).suffix.lower() in _IMAGE_SUFFIXES for n in names
                         if not n.endswith("/")):
            return ".zip-images"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return Path(filename).suffix.lower()


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def extract_document(document, data):
    """Text cục bộ, không gọi AI. Trả "" khi file không có lớp chữ (ảnh, scan)."""
    extension = sniff_extension(data, document.filename or "")
    if extension in _IMAGE_SUFFIXES or extension == ".zip-images":
        return ""                       # ảnh: để OCR lo
    name = f"cv-{document.pk}{extension}"
    upload = SimpleUploadedFile(name, data, content_type=document.mime_type or None)
    try:
        return extract_file(upload, max_bytes=25 * 1024 * 1024)
    except Exception:                               # noqa: BLE001
        if extension != ".docx":
            raise
        # python-docx đọc CẢ gói và chết vì một ảnh hỏng CRC hay thiếu
        # [Content_Types].xml, dù phần chữ còn nguyên — đọc thẳng XML.
        return _docx_xml_text(data)


def _docx_xml_text(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    parts = [n for n in archive.namelist() if n.startswith("word/") and n.endswith(".xml")
             and Path(n).stem.startswith(("document", "header", "footer"))]
    parts.sort(key=lambda n: (not Path(n).stem.startswith("document"), n))
    lines = []
    for name in parts:
        try:
            root = ElementTree.fromstring(archive.read(name))
        except (zipfile.BadZipFile, ElementTree.ParseError, KeyError):
            continue
        for paragraph in root.iter():
            if paragraph.tag.endswith("}p"):
                text = "".join(node.text or "" for node in paragraph.iter()
                               if node.tag.endswith("}t"))
                if text.strip():
                    lines.append(text)
    return "\n".join(lines)


#: Ảnh nhúng nhỏ hơn mức này là logo/icon, không phải trang CV.
_MIN_EMBEDDED_IMAGE_BYTES = 8 * 1024


def _ai_read(document, data, extracted, complete_fn=None):
    """Chuỗi AI cho file cục bộ không đọc được. Trả (text, completion) hoặc
    (None, None) khi file không có ảnh nào mà bản trích cục bộ vẫn dùng tạm được.

    1. Có ảnh trang (PDF, ảnh, gói ảnh, ảnh nhúng trong Word/Excel) → AI vision.
       Báo "không thấy chữ" thì đọc lại MỘT lần ở độ phân giải cao hơn: scan mờ,
       chữ nhỏ là lý do phổ biến nhất để lượt đầu trả rỗng.
    2. Không có ảnh (định dạng lạ, .doc cũ, file hỏng) → gom chuỗi chữ còn sót
       trong file và nhờ AI dựng lại nội dung CV.
    """
    try:
        images = _render_for_ocr(document, data)
    except Exception as exc:                        # noqa: BLE001
        log.info("Document %s: không dựng được ảnh để OCR (%s).", document.pk, exc)
        images = []
    if images:
        try:
            return _vision_ocr(document, images, complete_fn=complete_fn)
        except OcrEmpty:
            sharper = _render_for_ocr(document, data, zoom=2.5)
            if not sharper:
                raise
            return _vision_ocr(document, sharper, complete_fn=complete_fn)
    if extracted:
        return None, None
    raw = _binary_strings(data)
    if len(_CHUOI_CHU.findall(raw)) < 20:
        raise OcrEmpty("File không có ảnh trang và không còn chuỗi chữ nào đọc được.")
    completion = (complete_fn or complete)([
        {"role": "system", "content": SYSTEM_PROMPT + (
            "\nĐầu vào là các chuỗi chữ gom từ một file hỏng/định dạng cũ, lẫn rác "
            "nhị phân. Bỏ rác, giữ đúng nội dung CV theo thứ tự xuất hiện.")},
        {"role": "user", "content": raw[:60_000]},
    ], task=TASK, max_tokens=12_000)
    text = _clean_response(completion.text)
    if looks_like_ocr_empty(text) or len(text) < 20:
        raise OcrEmpty("AI không dựng lại được nội dung CV từ file.")
    return text, completion


def _binary_strings(data):
    """Chuỗi chữ đọc được trong file nhị phân: UTF-16LE (Word 97–2003) + UTF-8.

    Giải mã cả file theo từng bảng mã rồi nhặt đoạn chữ liền — phần nhị phân
    thành ký tự rác bị bỏ, phần chữ thật còn nguyên. Rác lọt qua để AI lọc.
    """
    out = []
    decoded = [data.decode("utf-8", errors="ignore"),
               data.decode("utf-16-le", errors="ignore"),
               data[1:].decode("utf-16-le", errors="ignore")]
    for text in decoded:
        for run in _TEXT_RUN.findall(text):
            run = " ".join(run.split())
            letters = sum(ch.isalpha() for ch in run)
            if letters >= 4 and letters >= len(run) * 0.5:
                out.append(run)
    return "\n".join(dict.fromkeys(out))


_TEXT_RUN = re.compile(r"[\w .,:;@()/+&%#'\-]{6,}", re.UNICODE)


def _vision_ocr(document, images, complete_fn=None):
    """OCR ảnh trang CV qua provider AI vision dùng cùng router và audit log."""
    if not images:
        raise OcrEmpty("File không có trang/ảnh nào để OCR.")
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
    if looks_like_ocr_empty(text):
        raise OcrEmpty(f"OCR không thấy chữ: {text[:120]}")
    if len(text) < 20:
        raise ValueError("AI OCR không trả về đủ văn bản CV.")
    return text, completion


def _render_for_ocr(document, data, zoom=1.5):
    """Chỉ gửi tối đa 10 trang/ảnh đã nén để có giới hạn chi phí rõ ràng."""
    extension = sniff_extension(data, document.filename or "")
    if extension == ".pdf":
        import fitz
        pdf = fitz.open(stream=data, filetype="pdf")
        images = []
        try:
            for page in list(pdf)[:10]:
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                images.append(pix.tobytes("jpeg"))
        finally:
            pdf.close()
        return images
    if extension in _IMAGE_SUFFIXES:
        return [_jpeg(data)]
    if extension == ".zip-images":
        # CV nộp dưới dạng gói ảnh chụp từng trang (đuôi .docx trên TopCV).
        archive = zipfile.ZipFile(io.BytesIO(data))
        names = sorted(n for n in archive.namelist()
                       if Path(n).suffix.lower() in _IMAGE_SUFFIXES)[:10]
        return [_jpeg(archive.read(name)) for name in names]
    if extension in {".docx", ".xlsx", ".pptx"}:
        # Word/Excel mà CV là ẢNH dán vào (chụp CV giấy, xuất từ app) — phần
        # chữ trống, nội dung nằm trong `*/media/`. Bỏ logo/icon nhỏ.
        archive = zipfile.ZipFile(io.BytesIO(data))
        images = []
        for info in sorted(archive.infolist(), key=lambda i: i.filename):
            if ("/media/" in info.filename
                    and Path(info.filename).suffix.lower() in _IMAGE_SUFFIXES
                    and info.file_size >= _MIN_EMBEDDED_IMAGE_BYTES):
                try:
                    images.append(_jpeg(archive.read(info.filename)))
                except Exception:                   # noqa: BLE001 - ảnh hỏng CRC
                    continue
            if len(images) >= 10:
                break
        return images
    return []


def _jpeg(data):
    from PIL import Image
    image = Image.open(io.BytesIO(data)).convert("RGB")
    image.thumbnail((1800, 2400))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=85, optimize=True)
    return output.getvalue()


def _clean_response(value):
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
