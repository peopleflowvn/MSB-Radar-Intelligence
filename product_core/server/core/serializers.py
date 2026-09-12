# -*- coding: utf-8 -*-
"""Kiểm tra dữ liệu Edge gửi lên.

Nguyên tắc: Hub không tin Edge. Edge chạy trên máy văn phòng, có thể là bản cũ,
bản lỗi hoặc bản đang thử nghiệm. Mọi thứ đi vào CSDL đều phải qua đây.
"""
import hashlib
import json

from accounts import privacy
from rest_framework import serializers

from .models import SourceRecord

# Các trường được nhấc từ payload ra thành cột, kèm độ dài tối đa. Payload vẫn
# là nguồn sự thật; đây chỉ là bản sao để tra cứu và hiển thị.
PROMOTED_COLUMNS = {
    "source": 40,
    "account": 200,
    "fullname": 200,
    "email": 200,
    "phone": 40,
    "position": 200,
}

ENTITY_SOURCE_RECORD = "source_record"
ENTITY_DOCUMENT = "document"
ALLOWED_ENTITY_TYPES = {ENTITY_SOURCE_RECORD, ENTITY_DOCUMENT}


class EdgeRegisterSerializer(serializers.Serializer):
    edge_id = serializers.CharField(max_length=64)
    hostname = serializers.CharField(max_length=200, required=False, allow_blank=True,
                                     default="")
    app_version = serializers.CharField(max_length=40, required=False, allow_blank=True,
                                        default="")

    def validate_edge_id(self, value):
        value = str(value or "").strip()
        if not value:
            raise serializers.ValidationError("Thiếu mã Edge.")
        return value


class SyncRecordSerializer(serializers.Serializer):
    """Một bản ghi trong lô.

    Trả về dict đã chuẩn hoá gồm payload, content_hash và các cột được nhấc ra,
    thay vì đối tượng model — việc quyết định thêm mới hay cập nhật thuộc về view.
    """

    entity_type = serializers.CharField(max_length=40)
    entity_key = serializers.CharField(max_length=300)
    idempotency_key = serializers.CharField(max_length=128, required=False,
                                            allow_blank=True, default="")

    def validate_entity_type(self, value):
        value = str(value or "").strip()
        if value not in ALLOWED_ENTITY_TYPES:
            raise serializers.ValidationError(
                f"Loại thực thể chưa được hỗ trợ: {value}")
        return value

    def validate_entity_key(self, value):
        value = str(value or "").strip()
        if not value:
            raise serializers.ValidationError("Thiếu entity_key.")
        return value

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Mỗi bản ghi phải là một đối tượng JSON.")
        validated = super().to_internal_value(data)

        # Giữ nguyên payload Edge gửi, trừ các trường thuộc về giao thức vận
        # chuyển. Cách này cho phép Edge bổ sung trường mới mà Hub không cần
        # phát hành lại — Hub chỉ ràng buộc phần nó thật sự dùng.
        payload = {k: v for k, v in data.items()
                   if k not in ("idempotency_key", "edge_id")}

        return {
            "entity_type": validated["entity_type"],
            "entity_key": validated["entity_key"],
            "payload": payload,
            "content_hash": content_hash(payload),
            "columns": promote_columns(payload),
        }


class SyncBatchSerializer(serializers.Serializer):
    """Khuôn của cả lô. **Không dùng để kiểm tra lô nhận từ Edge** — xem
    `core/views.py::edge_sync`.

    Kiểm cả lô một lượt nghĩa là một bản ghi hỏng làm hỏng cả 50 bản ghi. Hàm
    nhận lô kiểm từng bản ghi bằng `SyncRecordSerializer` riêng lẻ. Lớp này
    giữ lại vì nó là tài liệu sống về khuôn dữ liệu, và vì mã bên ngoài có thể
    đang dùng nó để sinh ví dụ.
    """

    edge_id = serializers.CharField(max_length=64, required=False, allow_blank=True,
                                    default="")
    records = SyncRecordSerializer(many=True, allow_empty=True)


def content_hash(payload):
    """Hash nội dung Hub tự tính, KHÔNG lấy từ Edge.

    Hub tự tính vì đây là cơ sở để phân biệt duplicate với updated. Tin vào hash
    do bên gửi cung cấp nghĩa là một Edge lỗi có thể khiến Hub bỏ qua dữ liệu đã
    thay đổi thật.

    edge_id bị loại vì nó không phải nội dung bản ghi — nếu tính vào, cùng một
    lượt ứng tuyển gửi từ hai Edge sẽ trông như hai nội dung khác nhau.
    """
    material = {k: v for k, v in payload.items()
                if k not in ("edge_id", "idempotency_key")}
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def promote_columns(payload):
    """Lấy các trường tra cứu ra khỏi payload, cắt cho vừa độ dài cột.

    Cắt chứ không từ chối: một cái tên dài bất thường không đáng để mất cả bản
    ghi, vì payload đầy đủ vẫn được lưu nguyên vẹn.
    """
    columns = {}
    for name, max_length in PROMOTED_COLUMNS.items():
        value = payload.get(name)
        columns[name] = "" if value is None else str(value)[:max_length]
    return columns


class SourceRecordSerializer(serializers.ModelSerializer):
    """Đọc bản ghi nguồn cho giao diện Hub — liên hệ **đã che**.

    Đây từng là lỗ hổng cuối cùng của lớp che PII (Master Plan mục 27): màn hình
    này trả email và số điện thoại **thô**, lật trang 200 dòng một lần, kèm tìm
    kiếm theo `email__icontains`. Vai trò Vận hành Edge — một vai trò *vận hành*,
    không phải nghiệp vụ — đọc được liên hệ của toàn bộ kho bằng cách lật trang.
    Đó đúng là kịch bản đọc hàng loạt mà cả cơ chế che sinh ra để chặn, và nó đi
    vòng qua toàn bộ `accounts/privacy.py`.

    Người vận hành cần biết **bản ghi có liên hệ hay không** để xác nhận dữ liệu
    về đủ — giá trị đã che trả lời được câu đó. Cần giá trị thật thì đi qua
    `POST /auth/contact-unlock/<person_id>/` như mọi nơi khác, nơi có đếm hạn
    mức và ghi vết.
    """

    edge_label = serializers.CharField(source="edge.label", read_only=True)
    edge_id = serializers.CharField(source="edge.edge_id", read_only=True, default="")
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    contact_masked = serializers.SerializerMethodField()

    class Meta:
        model = SourceRecord
        fields = ["id", "edge_label", "edge_id", "entity_type", "entity_key", "source", "account",
                  "fullname", "email", "phone", "contact_masked", "position",
                  "status", "revision", "first_seen_at", "last_seen_at"]

    def get_email(self, record):
        return privacy.mask_email(record.email)

    def get_phone(self, record):
        return privacy.mask_phone(record.phone)

    def get_contact_masked(self, record):
        return bool(record.email or record.phone)
