# -*- coding: utf-8 -*-
"""Đưa SourceRecord ở bàn nhận qua động cơ phân giải thành Person.

Chạy tách khỏi luồng HTTP nhận dữ liệu một cách có chủ đích: Edge chỉ cần biết
Hub đã nhận và lưu an toàn. Phân giải là việc của Hub, làm sau, làm lại được.

Nhờ tách như vậy, khi quy tắc phân giải thay đổi thì chạy lại trên toàn bộ dữ
liệu đã nhận — không phải xin Edge gửi lại 20 nghìn bản ghi.
"""
import logging

from core.models import SourceRecord
from django.db.models import F
from django.utils import timezone

from . import resolution

log = logging.getLogger(__name__)


def resolve_record(record):
    """Phân giải một SourceRecord. Trả về Resolution."""
    result = resolution.resolve(record.payload, source_record_id=str(record.pk))

    if result.outcome in (resolution.CREATED, resolution.MATCHED):
        record.person = result.person
        record.status = SourceRecord.STATUS_RESOLVED
        record.resolve_attempted_at = timezone.now()
        record.save(update_fields=["person", "status", "resolve_attempted_at"])
        _derive_talent(result.person)
    else:
        # CONFLICT và SKIPPED cố ý để nguyên trạng thái 'pending': cả hai đều là
        # việc chưa xong. Xung đột cần người xử lý; thiếu định danh thì có thể
        # lần đồng bộ sau Edge gửi thêm email/điện thoại và bản ghi tự phân giải.
        #
        # Nhưng PHẢI đóng dấu thời điểm đã thử. Không đóng dấu thì `resolve_pending`
        # chọn lại đúng những bản ghi này ở mọi lượt chạy, và sau khoảng 500 bản
        # ghi không phân giải được thì không bản ghi mới nào còn được xử lý nữa.
        record.resolve_attempted_at = timezone.now()
        record.save(update_fields=["resolve_attempted_at"])

    return result


def _derive_talent(person):
    """Dựng lại hồ sơ tuyển dụng sau khi có dữ liệu nguồn mới.

    Lỗi bị nuốt: phân giải Person đã xong và đã ghi. Để lỗi suy diễn hồ sơ làm hỏng
    bước đó nghĩa là bản ghi quay về 'pending' và sẽ được xử lý lại vô hạn.
    `derive_all()` chạy lại lúc nào cũng được nên không mất gì.
    """
    try:
        from talent.derive import derive
        derive(person)
    except Exception:                          # noqa: BLE001 — xem docstring
        log.exception("Không suy được TalentProfile cho Person %s", person.pk)
    _enqueue_extraction(person)


def _enqueue_extraction(person):
    """Đánh dấu Person cần trích xuất fact — CHỈ enqueue, không chạy inline (§21.3).

    Tắt mặc định: pipeline fact/provenance không tự chạy trên dữ liệu thật cho tới
    khi được phê duyệt (§19). Bật bằng INTEL_AUTO_ENQUEUE_EXTRACTION=1.
    """
    from django.conf import settings
    if not getattr(settings, "INTEL_AUTO_ENQUEUE_EXTRACTION", False):
        return
    try:
        from intel.queue import enqueue
        enqueue(person, batch="ingest")
    except Exception:                          # noqa: BLE001
        log.exception("Không enqueue được extraction cho Person %s", person.pk)


def resolve_pending(limit=500):
    """Phân giải các bản ghi đang chờ. Trả thống kê theo kết quả.

    Có `limit` để một lượt chạy không giữ khoá CSDL quá lâu.

    **Thứ tự là phần quan trọng nhất của hàm này.** Bản cũ dùng `order_by("pk")`,
    tức luôn lấy đúng 500 bản ghi pk thấp nhất. Vì `CONFLICT` và `SKIPPED` ở lại
    `pending` vĩnh viễn — và ứng viên không có email/điện thoại là chuyện thường
    trong dữ liệu thu thập thật — chỉ cần tích tụ 500 bản ghi như vậy là mọi
    lượt chạy sau đó xử lý lại đúng 500 bản ghi chết đó và **không bao giờ chạm
    tới bản ghi mới**. Hệ quả dây chuyền: không có Person → không có
    TalentProfile → tài liệu trong cùng lô nhận `retry` cho tới khi hết lượt.

    Nay xếp theo `resolve_attempted_at` với chưa-thử lên trước: hàng đợi xoay
    vòng, bản ghi mới luôn được ưu tiên, bản ghi cũ vẫn được thử lại.
    """
    stats = {resolution.CREATED: 0, resolution.MATCHED: 0,
             resolution.CONFLICT: 0, resolution.SKIPPED: 0,
             "processed": 0, "errors": 0}

    queryset = (SourceRecord.objects
                .filter(status=SourceRecord.STATUS_PENDING)
                .order_by(F("resolve_attempted_at").asc(nulls_first=True), "pk")[:limit])

    for record in queryset:
        try:
            result = resolve_record(record)
            stats[result.outcome] += 1
        except Exception:                       # noqa: BLE001
            # Một bản ghi hỏng không được làm dừng cả lô. Nó vẫn ở 'pending' nên
            # lần chạy sau sẽ thử lại sau khi lỗi được sửa.
            log.exception("Không phân giải được SourceRecord %s", record.pk)
            stats["errors"] += 1
        stats["processed"] += 1

    return stats
