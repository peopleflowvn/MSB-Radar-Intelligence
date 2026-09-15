# -*- coding: utf-8 -*-
"""Chuyển bản ghi Edge thành payload gửi Hub, và tính hash nội dung.

Hai bảo đảm mà phần còn lại của hệ thống dựa vào:

1. entity_key ổn định. Bộ ba (source, account, cv_id) chính là khoá chính của
   bảng candidates, nên một lượt ứng tuyển luôn ánh xạ về đúng một hàng outbox.

2. payload_hash chỉ đổi khi NỘI DUNG GỬI ĐI đổi. Nhờ vậy quét lại toàn bộ CSDL
   là thao tác rẻ: chỉ những bản ghi thật sự thay đổi mới được xếp hàng lại.
   Vì thế hash được tính trên payload đã chuẩn hoá, không phải trên hàng CSDL
   thô — cột nội bộ như updated_at đổi liên tục nhưng không ảnh hưởng Hub.
"""
import hashlib
import json
import os

# Các trường Edge gửi lên Hub cho một lượt ứng tuyển. Cố ý là danh sách tường
# minh chứ không phải "mọi cột": thêm cột nội bộ vào candidates không được âm
# thầm làm mọi bản ghi có vẻ như đã thay đổi và kích hoạt đồng bộ lại toàn bộ.
CANDIDATE_FIELDS = (
    "source", "account", "cv_id",
    # `email`/`phone` = liên hệ của CHÍNH ứng viên (Hub dùng làm định danh
    # Person). `cv_emails`/`cv_phones` = mọi liên hệ đọc được trong text CV,
    # trong đó thường có người tham chiếu — Hub phân xử, KHÔNG tự gắn.
    "fullname", "email", "phone", "cv_emails", "cv_phones", "position",
    "campaign_id", "applied_at", "applied_ts", "apply_source", "status",
    "gender", "birth_year", "marital_status", "experience", "years_experience",
    "address", "city", "district", "desired_location",
    "current_title", "job_level", "desired_level", "desired_position", "job_type",
    "education", "foreign_language", "expected_salary", "current_salary",
    "skills", "last_company", "labels", "note",
    "candidate_id", "resume_id", "profile_type",
    "attachment_name", "attachment_mime",
    "cv_url", "first_seen", "source_payload",
)

ENTITY_SOURCE_RECORD = "source_record"
ENTITY_DOCUMENT = "document"

KEY_SEPARATOR = "|"

# Trường của một tài liệu (file CV). Cố ý KHÔNG có nội dung file: file được tải
# lên ở pha hai, và chỉ khi Hub báo là chưa có. Kho CV ~20.000 hồ sơ ≈ 4 GB;
# gửi kèm file trong mỗi lô nghĩa là mỗi lần quét lại đẩy lại toàn bộ 4 GB đó.
DOCUMENT_FIELDS = (
    "source", "account", "cv_id",
    "filename", "sha256", "file_size", "file_format", "mime_type",
    "parse_status", "quality_score", "text_length",
    "observed_at",
)


def candidate_key(row):
    """entity_key của một lượt ứng tuyển: đúng khoá chính của bảng candidates."""
    return KEY_SEPARATOR.join((
        str(row.get("source") or ""),
        str(row.get("account") or ""),
        str(row.get("cv_id") or ""),
    ))


def candidate_payload(row, edge_id="", extensions=None):
    """Payload Hub nhận cho một lượt ứng tuyển.

    Giá trị None được chuẩn hoá thành chuỗi rỗng để hash ổn định giữa các lần
    chạy — SQLite trả None còn JSON trả null, hai thứ đó phải cho cùng một hash.
    """
    payload = {name: _clean(row.get(name)) for name in CANDIDATE_FIELDS}
    # Giữ dữ liệu mở rộng có version để Hub có thể tái chiếu khi schema/parser
    # tiến hóa. Đây là dữ liệu nguồn, không tự động coi là fact đã duyệt.
    if extensions:
        payload["extensions"] = extensions
    payload["entity_type"] = ENTITY_SOURCE_RECORD
    payload["entity_key"] = candidate_key(row)
    if edge_id:
        payload["edge_id"] = str(edge_id)
    return payload


MIME_BY_EXTENSION = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def document_payload(row, edge_id=""):
    """Payload cho một file CV.

    `entity_key` TRÙNG với entity_key của lượt ứng tuyển mang nó — nhờ vậy Hub tìm
    được bản ghi nguồn tương ứng và qua đó là Person. Hai loại thực thể phân biệt
    nhau bằng `entity_type`, không phải bằng khoá.

    Cùng một người ứng tuyển nhiều lần ở nhiều thời điểm sẽ có nhiều file khác
    nhau; mỗi file là một tài liệu riêng, và Hub gom chúng theo Person.
    """
    payload = {name: _clean(row.get(name)) for name in DOCUMENT_FIELDS}
    payload["entity_type"] = ENTITY_DOCUMENT
    payload["entity_key"] = candidate_key(row)
    payload["document_type"] = "cv"

    if not payload.get("mime_type"):
        extension = str(row.get("file_format")
                        or os.path.splitext(str(row.get("filename") or ""))[1]
                        ).lstrip(".").lower()
        payload["mime_type"] = MIME_BY_EXTENSION.get(extension, "")

    # Text đã bóc tách đi kèm metadata: nó là thứ Hub cần để tìm kiếm, và nhẹ hơn
    # file gốc rất nhiều nên không đáng phải thêm một pha nữa.
    text = str(row.get("full_text") or "")
    if text:
        payload["parsed_text"] = text[:200_000]

    if edge_id:
        payload["edge_id"] = str(edge_id)
    return payload


def document_key(row):
    """entity_key của tài liệu — cùng khoá với lượt ứng tuyển mang nó."""
    return candidate_key(row)


def payload_hash(payload):
    """Hash ổn định của payload.

    edge_id bị loại khỏi phép tính: nó không phải nội dung bản ghi, và giữ nó
    lại sẽ khiến mọi thứ có vẻ như đã thay đổi nếu danh tính Edge được tạo lại.
    """
    material = {k: v for k, v in payload.items() if k != "edge_id"}
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def idempotency_key(edge_id, entity_type, entity_key, content_hash):
    """Khoá chống trùng gửi kèm mỗi bản ghi.

    Gồm cả content_hash để gửi lại đúng nội dung cũ là no-op ở phía Hub, còn
    nội dung đã sửa thì vẫn được nhận như một bản cập nhật.
    """
    raw = KEY_SEPARATOR.join((str(edge_id), str(entity_type),
                              str(entity_key), str(content_hash)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clean(value):
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    return str(value)
