# -*- coding: utf-8 -*-
"""Nhận tài liệu (file CV) từ Edge.

Đồng bộ hai pha, và lý do rất cụ thể: kho CV hiện tại khoảng 20.000 hồ sơ, cỡ trung
bình 200 KB — tức ~4 GB. Gửi kèm file trong mỗi lô đồng bộ nghĩa là mỗi lần quét lại
sẽ đẩy lại toàn bộ 4 GB đó qua đường truyền văn phòng.

    Pha 1   Edge gửi METADATA (sha256, tên file, cỡ, text đã bóc tách) trong lô
            đồng bộ bình thường. Hub tạo bản ghi Document và trả `needs_file`.
    Pha 2   Edge CHỈ tải lên những file Hub báo là chưa có.

Vì kho file đánh địa chỉ theo nội dung, Hub trả lời "đã có file này" tức thì. Một
CV không đổi thì vĩnh viễn không bao giờ được gửi lại.

Phiên bản CV tự sinh ra từ mã băm — xem docstring của `people.models.Document`.
"""
import logging

from django.db import transaction
from people.models import Document
from people.parsed_text import save_parsed_text

from .storage import content_key, get_storage, sha256_of

log = logging.getLogger(__name__)

# Cỡ file tối đa nhận được. CV lớn hơn mức này gần như chắc chắn là quét ảnh độ
# phân giải quá cao, hoặc file gửi nhầm.
MAX_FILE_BYTES = 25 * 1024 * 1024


class DocumentError(Exception):
    pass


class BinaryParser:
    """Đọc thân yêu cầu nhị phân thô.

    Không dùng FileUploadParser của DRF: nó bắt buộc phải có tên file trong
    Content-Disposition và ném ParseError nếu thiếu. Ở đây tên file là tuỳ chọn
    (nội dung được đánh địa chỉ theo mã băm, không theo tên), nên ràng buộc đó
    chỉ tạo ra một cách thất bại không cần thiết.
    """

    media_type = "application/octet-stream"

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read()


@transaction.atomic
def ingest_metadata(source_record, payload):
    """Tạo/cập nhật Document từ metadata. Trả (document, needs_file).

    `needs_file` là True khi Hub chưa có nội dung file, tức Edge cần tải lên ở pha 2.
    """
    person = source_record.person
    if person is None:
        # Bản ghi nguồn chưa phân giải được thành Person. Không có chỗ để gắn tài
        # liệu — Edge sẽ gửi lại ở lượt sau khi Person đã có.
        raise DocumentError("Bản ghi nguồn chưa được phân giải thành Person.")

    digest = str(payload.get("sha256") or "").strip().lower()
    if len(digest) != 64:
        raise DocumentError(f"sha256 không hợp lệ: {payload.get('sha256')!r}")

    person = person.canonical()

    document, created = Document.objects.get_or_create(
        person=person, sha256=digest,
        defaults={
            "document_type": str(payload.get("document_type") or "cv")[:40],
            "source": str(payload.get("source") or "")[:40],
            "filename": str(payload.get("filename") or "")[:300],
            "mime_type": str(payload.get("mime_type") or "")[:100],
            "file_size": _int(payload.get("file_size")),
            "observed_at": _timestamp(payload.get("observed_at")
                                      or payload.get("applied_ts")),
        })

    if not created:
        # Đã có file này rồi. Chỉ bổ sung chỗ còn trống, không ghi đè: bản ghi đầu
        # tiên nhìn thấy file mang bối cảnh đúng nhất về nguồn gốc của nó.
        changed = []
        if not document.filename and payload.get("filename"):
            document.filename = str(payload["filename"])[:300]
            changed.append("filename")
        if not document.file_size:
            document.file_size = _int(payload.get("file_size"))
            changed.append("file_size")
        observed = _timestamp(payload.get("observed_at") or payload.get("applied_ts"))
        if observed and (document.observed_at is None or observed < document.observed_at):
            # Giữ mốc SỚM NHẤT: đó là lần đầu phiên bản CV này xuất hiện.
            document.observed_at = observed
            changed.append("observed_at")
            # `source` phải mô tả CÙNG sự kiện với `observed_at`. Không cập nhật
            # cùng lúc thì giao diện hiện "v2 · 20/6/2025 · careerviet" trong khi
            # lượt ứng tuyển ngày đó lại ở VietnamWorks — hai trường nói về hai
            # chuyện khác nhau, và người đọc không có cách nào biết.
            if payload.get("source"):
                document.source = str(payload["source"])[:40]
                changed.append("source")
            if payload.get("filename"):
                document.filename = str(payload["filename"])[:300]
                if "filename" not in changed:
                    changed.append("filename")
        if changed:
            document.save(update_fields=changed + ["updated_at"])

    text = str(payload.get("parsed_text") or "")
    if text:
        # Mọi kết quả khác nhau đều được giữ; text trùng chỉ tạo thêm liên kết nguồn.
        save_parsed_text(document, text, origin="edge",
                         quality_score=float(payload.get("quality_score") or 0.7),
                         provider="edge", model=str(payload.get("parser") or "")[:100])

    document.source_records.add(source_record)

    if not document.storage_key:
        # Kho đánh địa chỉ theo NỘI DUNG, nên nếu bất kỳ Document nào khác đã có
        # đúng mã băm này thì các byte đã nằm sẵn trong kho — không cần Edge tải
        # lên lần nữa, chỉ cần trỏ tới.
        #
        # Không làm bước này thì mất file thật sự: Edge khử trùng lặp trong phạm
        # vi một lô theo sha256, nên khi hai lượt ứng tuyển cùng file thuộc hai
        # Person chưa được gộp (chuyện thường — một người khớp bằng email ở
        # nguồn này, bằng điện thoại ở nguồn kia), Edge chỉ tải một lần rồi đánh
        # dấu cả hai là đã gửi. Person còn lại giữ `storage_key` rỗng VĨNH VIỄN,
        # vì nội dung không đổi nên `enqueue_sync` không bao giờ xếp lại hàng.
        shared = (Document.objects
                  .filter(sha256=digest)
                  .exclude(pk=document.pk)
                  .exclude(storage_key="")
                  .values_list("storage_key", flat=True)
                  .first())
        if shared and get_storage().exists(shared):
            document.storage_key = shared
            document.save(update_fields=["storage_key", "updated_at"])

    needs_file = not document.storage_key
    if not needs_file and not document.primary_text_version_id and not document.parsed_text:
        document_id = document.pk
        transaction.on_commit(lambda: _parse_document_quietly(document_id))
    return document, needs_file


def _parse_document_quietly(document_id):
    try:
        from .cv_parsing import parse_missing_document
        document = Document.objects.get(pk=document_id)
        parse_missing_document(document)
    except Exception:  # noqa: BLE001 - đồng bộ metadata vẫn phải thành công
        log.exception("Không khởi động được parsing bù cho Document %s", document_id)


def store_file(person, digest, data, filename=""):
    """Ghi nội dung file vào kho (pha 2). Trả về Document đã cập nhật."""
    digest = str(digest or "").strip().lower()
    if len(digest) != 64:
        raise DocumentError("sha256 không hợp lệ.")
    if not data:
        raise DocumentError("File rỗng.")
    if len(data) > MAX_FILE_BYTES:
        raise DocumentError(
            f"File quá lớn: {len(data)} byte, tối đa {MAX_FILE_BYTES}.")

    # Tự băm lại thay vì tin Edge. Nếu không kiểm, một Edge lỗi có thể ghi nội
    # dung của người này dưới mã băm của người khác — và vì kho đánh địa chỉ theo
    # nội dung, sai lệch đó sẽ lan sang mọi Document dùng chung mã băm ấy.
    actual = sha256_of(data)
    if actual != digest:
        raise DocumentError(
            f"Nội dung không khớp mã băm (nhận {digest[:12]}…, thực tế {actual[:12]}…).")

    document = Document.objects.filter(person=person.canonical(), sha256=digest).first()
    if document is None:
        raise DocumentError("Chưa có metadata cho file này; hãy đồng bộ metadata trước.")

    key = content_key(digest, filename or document.filename)
    storage = get_storage()
    if not storage.exists(key):
        storage.save(key, data)

    if not document.storage_key:
        document.storage_key = key
        document.file_size = document.file_size or len(data)
        document.save(update_fields=["storage_key", "file_size", "updated_at"])

    # Đây là đường đi THƯỜNG của một file mới: Edge gửi metadata (chưa có text
    # vì bóc lỗi) rồi mới tải file lên ở pha hai. `ingest_metadata` không kích
    # hoạt được parsing bù vì lúc đó file chưa tồn tại, nên nếu ở đây cũng không
    # gọi thì Hub cất file vào kho rồi DỪNG — CV Edge bóc lỗi không bao giờ được
    # AI đọc lại, đúng thứ đáng lẽ Hub phải làm.
    if not document.primary_text_version_id and not document.parsed_text:
        document_id = document.pk
        transaction.on_commit(lambda: _parse_document_quietly(document_id))
    return document


def versions(person, document_type="cv"):
    """Các phiên bản CV của một người, cũ nhất trước.

    Đây là câu trả lời cho "cho tôi xem tất cả CV của người này qua các thời điểm".
    """
    return list(Document.objects
                .filter(person=person.canonical(), document_type=document_type)
                .order_by("observed_at", "created_at")
                .prefetch_related("source_records"))


def _int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _timestamp(value):
    from datetime import datetime

    from django.utils import timezone
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[:19], pattern)
        except (ValueError, TypeError):
            continue
        return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
    return None
