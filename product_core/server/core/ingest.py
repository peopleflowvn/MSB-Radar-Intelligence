# -*- coding: utf-8 -*-
"""Ghi một bản ghi vào BÀN NHẬN (`SourceRecord`) — chèn mới hoặc cập nhật.

Tách khỏi `core/views.py::edge_sync` một cách có chủ đích: Edge không phải là
producer duy nhất của bàn nhận nữa. Luồng nhập liệu thủ công (`intake/`) cần đúng
ngữ nghĩa chèn/cập nhật/khử trùng này, nhưng KHÔNG cần các chuỗi trạng thái mà
giao thức đồng bộ Edge quy định. Vì vậy hàm ở đây trả `outcome` trung tính
(`created`/`duplicate`/`updated`) và để người gọi tự dịch sang ngôn ngữ của mình.

Khử trùng lặp nằm ở CSDL: ràng buộc `uq_source_record_entity` trên
`(edge, entity_type, entity_key)`. Cùng một thực thể gửi lại là cập nhật, không
phải thêm mới — kể cả khi hai yêu cầu chạy song song.
"""
from django.db import transaction

from .models import SourceRecord

CREATED = "created"
DUPLICATE = "duplicate"
UPDATED = "updated"


def upsert_source_record(edge, *, entity_type, entity_key, payload, content_hash,
                         columns):
    """Chèn hoặc cập nhật một `SourceRecord`. Trả `(record, outcome)`.

    `outcome`:
      - `created`   — chưa từng thấy `(edge, entity_type, entity_key)` này.
      - `duplicate` — đã có và `content_hash` không đổi; chỉ đóng dấu `last_seen_at`.
      - `updated`   — đã có nhưng nội dung đổi; `revision` tăng, `status` về
        `pending` để phân giải lại.

    Ném `IntegrityError` khi hai lượt ghi song song đụng ràng buộc duy nhất —
    đây là tranh chấp tạm thời, người gọi nên coi là "thử lại", không phải lỗi
    vĩnh viễn. Các lỗi CSDL khác cũng bay lên để người gọi quyết.

    `columns` là các trường tra cứu đã nhấc khỏi payload (xem
    `serializers.promote_columns`); payload vẫn là nguồn sự thật.
    """
    with transaction.atomic():
        existing = (SourceRecord.objects
                    .select_for_update()
                    .filter(edge=edge, entity_type=entity_type, entity_key=entity_key)
                    .first())

        if existing is None:
            created = SourceRecord.objects.create(
                edge=edge,
                entity_type=entity_type,
                entity_key=entity_key,
                payload=payload,
                content_hash=content_hash,
                **columns)
            return created, CREATED

        if existing.content_hash == content_hash:
            # Gửi lại đúng nội dung cũ. Đường đi bình thường khi producer thử lại
            # sau lỗi mạng, hoặc khi cùng một hồ sơ được nhập lại từ một file khác.
            existing.save(update_fields=["last_seen_at"])
            return existing, DUPLICATE

        existing.payload = payload
        existing.content_hash = content_hash
        for name, value in columns.items():
            setattr(existing, name, value)
        existing.revision += 1
        # Nội dung đổi thì kết quả phân giải cũ không còn đáng tin.
        existing.status = SourceRecord.STATUS_PENDING
        existing.save()
        return existing, UPDATED
