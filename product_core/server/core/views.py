# -*- coding: utf-8 -*-
"""Các endpoint Edge gọi.

Hiện thực đúng hợp đồng đã chốt ở docs/SYNC.md mục 5 — phía Edge đã nói giao
thức này từ Phase 2, nên các chuỗi trạng thái ở đây không được tuỳ tiện đổi.
"""
import logging

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import ingest as core_ingest
from .auth import require_edge
from .documents import BinaryParser, DocumentError, ingest_metadata, store_file
from .models import SourceRecord
from .serializers import (ENTITY_DOCUMENT, ENTITY_SOURCE_RECORD,
                          EdgeRegisterSerializer, SyncRecordSerializer)
from .permissions import IsAuthenticatedEdge

log = logging.getLogger(__name__)


def _first_error(errors):
    """Lấy một câu lỗi đọc được từ cây lỗi của DRF.

    Edge ghi chuỗi này vào nhật ký cho người dùng đọc, nên nó phải là một câu
    chứ không phải một dict lồng nhau.
    """
    if isinstance(errors, dict):
        for value in errors.values():
            found = _first_error(value)
            if found:
                return found
        return "Bản ghi không hợp lệ."
    if isinstance(errors, (list, tuple)):
        for item in errors:
            found = _first_error(item)
            if found:
                return found
        return "Bản ghi không hợp lệ."
    return str(errors)[:300]

# Chuỗi trạng thái Edge hiểu được (Master Plan mục 37). Edge coi accepted/
# duplicate/updated là xong, retry/conflict là hẹn lại, còn lại là lỗi vĩnh viễn.
ACCEPTED = "accepted"
DUPLICATE = "duplicate"
UPDATED = "updated"
RETRY = "retry"
REJECTED = "rejected"


@api_view(["GET"])
@permission_classes([AllowAny])
def liveness(request):
    """Hub có sống không. Không cần xác thực — dùng cho health check hạ tầng.

    Cố ý không chạm CSDL: nó trả lời câu hỏi "tiến trình còn chạy không", còn
    "phụ thuộc có khoẻ không" là việc của /edge/health/.
    """
    return Response({"ok": True, "service": "msb-radar-hub"})


@api_view(["GET"])
@permission_classes([IsAuthenticatedEdge])
def edge_health(request):
    """Edge kiểm tra Hub sống và khoá API còn hiệu lực. Tương ứng client.health()."""
    edge = require_edge(request)
    edge.touch()
    return Response({
        "ok": True,
        "edge": {
            "label": edge.label,
            "edge_id": edge.edge_id or "",
            "registered": bool(edge.registered_at),
        },
        "server_time": timezone.now().isoformat(),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticatedEdge])
def edge_register(request):
    """Edge tự khai báo. Idempotent theo edge_id.

    Bản ghi Edge được quản trị viên tạo trước rồi cấp khoá; edge_id do ứng dụng
    Edge sinh ra và được gắn ở lần gọi này. Gọi lại chỉ cập nhật tên máy/phiên bản.
    """
    edge = require_edge(request)
    form = EdgeRegisterSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data
    incoming_id = data["edge_id"]

    if edge.edge_id and edge.edge_id != incoming_id:
        # Khoá này đã gắn với một bản cài khác. Gần như chắc chắn là khoá bị
        # dùng lại trên máy thứ hai — từ chối thay vì âm thầm cướp danh tính.
        log.warning("Edge %s (%s) bị dùng khoá với edge_id khác: %s",
                    edge.pk, edge.edge_id, incoming_id)
        return Response(
            {"detail": "Khoá API này đã gắn với một bản cài Edge khác. "
                       "Hãy cấp khoá riêng cho máy này."},
            status=status.HTTP_409_CONFLICT)

    already = bool(edge.edge_id)
    edge.edge_id = incoming_id
    edge.hostname = data.get("hostname") or edge.hostname
    edge.app_version = data.get("app_version") or edge.app_version
    edge.last_seen_at = timezone.now()
    if not edge.registered_at:
        edge.registered_at = edge.last_seen_at

    try:
        edge.save()
    except IntegrityError:
        # `Edge.edge_id` là duy nhất. Kiểm tra rồi mới ghi để lại một khe hở:
        # hai lần khai báo đồng thời cùng một `edge_id` đều thấy chưa ai dùng,
        # đều ghi, và lần sau đụng ràng buộc — trả 500 cho một tình huống có
        # câu trả lời rõ ràng là 409.
        #
        # Để CSDL phán quyết rồi dịch lỗi, thay vì hỏi trước rồi hy vọng.
        log.warning("Trùng edge_id %s khi khai báo Edge %s", incoming_id, edge.pk)
        return Response({"detail": "Mã Edge này đã thuộc về một Edge khác."},
                        status=status.HTTP_409_CONFLICT)

    return Response({
        "ok": True,
        "status": DUPLICATE if already else ACCEPTED,
        "edge": {"label": edge.label, "edge_id": edge.edge_id},
    })


@api_view(["POST"])
@permission_classes([IsAuthenticatedEdge])
def edge_sync(request):
    """Nhận một lô bản ghi từ Edge.

    Trả kết quả cho TỪNG bản ghi, không phải một trạng thái chung cho cả lô: một
    bản ghi hỏng không được kéo theo cả lô phải gửi lại, nếu không một hàng lỗi
    vĩnh viễn sẽ chặn hàng đợi của Edge mãi mãi.

    Lưu bền vững và khử trùng lặp trước, phân giải Person sau — xem _resolve_quietly().
    """
    edge = require_edge(request)

    raw_records = request.data.get("records")
    if not isinstance(raw_records, list):
        return Response({"detail": "Thiếu danh sách bản ghi."},
                        status=status.HTTP_400_BAD_REQUEST)

    # Chặn kích thước lô TRƯỚC khi kiểm tra từng bản ghi: kiểm rồi mới chặn
    # nghĩa là đã bỏ công phân tích, kiểm tra và băm sha256 toàn bộ lô — đúng
    # phần việc mà giới hạn này sinh ra để tránh.
    if len(raw_records) > settings.EDGE_SYNC_MAX_BATCH:
        return Response(
            {"detail": f"Lô quá lớn: {len(raw_records)} bản ghi, "
                       f"tối đa {settings.EDGE_SYNC_MAX_BATCH}."},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    # Kiểm tra TỪNG bản ghi, không phải cả lô một lượt.
    #
    # Bản cũ dùng `SyncBatchSerializer(...).is_valid(raise_exception=True)`, tức
    # là một bản ghi hỏng — `entity_type` lạ từ một Edge mới hơn, `entity_key`
    # rỗng, một dòng không phải dict — làm HTTP 400 cho **cả 50 bản ghi**. Edge
    # coi 400 là lỗi vĩnh viễn và đánh dấu toàn bộ lô `failed`, không backoff,
    # không đếm lần thử. Điều đó mâu thuẫn trực tiếp với chính docstring của hàm
    # này và với `docs/SYNC.md` mục 5.
    #
    # Nay bản ghi hỏng nhận `rejected` riêng, phần còn lại của lô vẫn được lưu.
    records, results = [], []
    for index, item in enumerate(raw_records):
        row = SyncRecordSerializer(data=item)
        if row.is_valid():
            records.append(row.validated_data)
            continue
        raw = item if isinstance(item, dict) else {}
        results.append({
            "entity_type": str(raw.get("entity_type") or "")[:40],
            "entity_key": str(raw.get("entity_key") or f"#{index}")[:300],
            "status": REJECTED,
            "detail": _first_error(row.errors),
        })

    # Bản ghi nguồn phải được lưu VÀ phân giải thành Person trước, vì tài liệu
    # cần một Person để gắn vào. Cùng một lô có thể chứa cả hai loại.
    documents = []
    for record in records:
        if record["entity_type"] == ENTITY_DOCUMENT:
            documents.append(record)
        else:
            results.append(_ingest(edge, record))

    edge.touch()
    _resolve_quietly()

    for record in documents:
        results.append(_ingest_document(edge, record))

    return Response({"ok": True, "results": results})


@api_view(["POST"])
@permission_classes([IsAuthenticatedEdge])
def edge_data_report(request):
    """Nhận số đếm không PII để đối soát Edge và Hub, không đoán từ heartbeat."""
    edge = require_edge(request)
    raw = request.data if isinstance(request.data, dict) else {}
    report = {}
    for section in ("candidates", "documents", "outbox"):
        values = raw.get(section)
        if not isinstance(values, dict):
            continue
        clean = {}
        for key, value in values.items():
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= number <= 100_000_000:
                clean[str(key)[:50]] = number
        report[section] = clean
    report["db_schema_version"] = str(raw.get("db_schema_version") or "")[:30]
    edge.data_report = report
    edge.data_reported_at = timezone.now()
    edge.last_seen_at = edge.data_reported_at
    edge.save(update_fields=["data_report", "data_reported_at", "last_seen_at", "updated_at"])
    return Response({"ok": True, "reported_at": edge.data_reported_at})


def _resolve_quietly():
    """Phân giải các bản ghi vừa nhận thành Person.

    Chạy SAU khi đã lưu, và mọi lỗi đều bị nuốt: Edge đã hoàn thành phần việc
    của nó khi dữ liệu nằm an toàn trong bàn nhận. Để lỗi phân giải làm hỏng
    phản hồi sẽ khiến Edge gửi lại những bản ghi vốn đã lưu thành công.

    Bản ghi chưa phân giải được vẫn ở 'pending', nên resolve_pending() chạy lại
    lúc nào cũng được — kể cả sau khi quy tắc phân giải thay đổi.
    """
    try:
        from people.ingest import resolve_pending
        resolve_pending(limit=settings.EDGE_SYNC_MAX_BATCH)
    except Exception:                            # noqa: BLE001 — xem docstring
        log.exception("Phân giải Person thất bại sau khi nhận đồng bộ")


def _ingest_document(edge, record):
    """Nhận metadata một tài liệu (pha 1 của đồng bộ file).

    `entity_key` của tài liệu trùng với `entity_key` của lượt ứng tuyển mang nó —
    nhờ vậy tìm được bản ghi nguồn tương ứng, và qua đó là Person.

    Trả thêm cờ `needs_file`: Edge chỉ tải nội dung lên khi Hub báo là chưa có.
    Không có cờ này thì mỗi lần quét lại sẽ đẩy lại toàn bộ ~4 GB CV.
    """
    entity_key = record["entity_key"]
    try:
        source_record = SourceRecord.objects.filter(
            edge=edge, entity_type=ENTITY_SOURCE_RECORD, entity_key=entity_key).first()
        if source_record is None:
            # Lượt ứng tuyển chưa tới, hoặc chưa phân giải. Bảo Edge thử lại —
            # thứ tự trong một lô không đảm bảo, và lô sau sẽ có đủ.
            return _doc_result(entity_key, RETRY,
                               detail="Chưa có bản ghi nguồn tương ứng.")

        document, needs_file = ingest_metadata(source_record, record["payload"])
        return _doc_result(entity_key, ACCEPTED, pk=document.pk,
                           needs_file=needs_file, sha256=document.sha256)
    except DocumentError as exc:
        # Chưa phân giải được Person là tình trạng tạm thời, không phải dữ liệu sai.
        retryable = "phân giải" in str(exc)
        return _doc_result(entity_key, RETRY if retryable else REJECTED,
                           detail=str(exc)[:300])
    except Exception as exc:                     # noqa: BLE001
        log.exception("Không nhận được tài liệu %s từ Edge %s", entity_key, edge.pk)
        return _doc_result(entity_key, REJECTED, detail=str(exc)[:300])


def _doc_result(entity_key, state, pk=None, detail="", needs_file=None, sha256=""):
    row = {"entity_key": entity_key, "entity_type": ENTITY_DOCUMENT, "status": state}
    if pk is not None:
        row["id"] = str(pk)
    if detail:
        row["detail"] = detail
    if needs_file is not None:
        row["needs_file"] = needs_file
    if sha256:
        row["sha256"] = sha256
    return row


@api_view(["POST"])
@permission_classes([IsAuthenticatedEdge])
@parser_classes([BinaryParser])
def edge_document_upload(request, sha256):
    """Nhận nội dung file (pha 2). Chỉ những file Hub báo `needs_file`.

    Nhận thân yêu cầu dạng nhị phân thô thay vì multipart: Edge gửi đúng một file
    mỗi lần, và multipart chỉ thêm một tầng phân tích cú pháp không cần thiết.
    """
    edge = require_edge(request)
    entity_key = str(request.query_params.get("entity_key") or "")

    source_record = SourceRecord.objects.filter(
        edge=edge, entity_type=ENTITY_SOURCE_RECORD, entity_key=entity_key).first()
    if source_record is None or source_record.person is None:
        return Response({"detail": "Chưa có bản ghi nguồn đã phân giải cho khoá này."},
                        status=status.HTTP_409_CONFLICT)

    raw = request.data if isinstance(request.data, bytes) else request.body

    try:
        document = store_file(source_record.person, sha256, raw,
                              filename=request.query_params.get("filename", ""))
    except DocumentError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # Edge chỉ xác nhận file đã nằm an toàn trong kho. Worker Hub xử lý preview/OCR/AI
    # độc lập để một provider chậm không làm timeout đồng bộ hoặc kích hoạt gọi AI trùng.
    edge.touch()
    return Response({"ok": True, "id": str(document.pk),
                     "storage_key": document.storage_key,
                     "size": document.file_size})


_OUTCOME_TO_STATUS = {
    core_ingest.CREATED: ACCEPTED,
    core_ingest.DUPLICATE: DUPLICATE,
    core_ingest.UPDATED: UPDATED,
}


def _ingest(edge, record):
    """Lưu một bản ghi. Không bao giờ ném lỗi ra ngoài — trả trạng thái cho Edge.

    Một bản ghi hỏng chỉ được làm hỏng chính nó. Để ngoại lệ bay lên sẽ khiến cả
    lô trả 500 và Edge gửi lại toàn bộ, kể cả những bản đã lưu thành công.

    Phần chèn/cập nhật/khử trùng nằm ở `core.ingest.upsert_source_record` — dùng
    chung với luồng nhập liệu thủ công. Ở đây chỉ dịch kết quả sang chuỗi trạng
    thái Edge hiểu được và xử lý tranh chấp thành `retry`.
    """
    entity_key = record["entity_key"]
    try:
        rec, outcome = core_ingest.upsert_source_record(
            edge,
            entity_type=record["entity_type"],
            entity_key=entity_key,
            payload=record["payload"],
            content_hash=record["content_hash"],
            columns=record["columns"])
        return _result(entity_key, _OUTCOME_TO_STATUS[outcome], rec.pk)

    except IntegrityError as exc:
        # `select_for_update()` KHÔNG khoá gì khi chưa có hàng nào khớp, nên hai
        # lượt đồng bộ song song từ cùng một Edge đều thấy `existing is None`,
        # đều `create()`, và một trong hai đụng `uq_source_record_entity`.
        #
        # Đây là tranh chấp tạm thời, không phải bản ghi hỏng: lần gửi lại sẽ
        # thấy hàng đã tồn tại và trả `duplicate`. Trả `rejected` ở đây khiến
        # Edge đánh dấu thất bại vĩnh viễn một bản ghi mà Hub sẵn sàng nhận.
        log.warning("Tranh chấp khi lưu %s từ Edge %s: %s", entity_key, edge.pk, exc)
        return _result_with_type(entity_key, RETRY, record["entity_type"],
                                 detail="Bản ghi đang được lưu bởi một lượt khác.")
    except Exception as exc:                     # noqa: BLE001 — xem docstring
        # Lỗi CSDL tạm thời (deadlock, mất kết nối, hết thời gian chờ khoá) cũng
        # rơi vào đây. `rejected` là vĩnh viễn ở phía Edge, nên một lần nghẽn
        # thoáng qua sẽ làm mất hẳn bản ghi mà Hub hoàn toàn nhận được ở lần
        # sau. `retry` có backoff và có trần số lần thử — mất nhiều nhất là một
        # ít thời gian, thay vì mất dữ liệu.
        log.exception("Không lưu được bản ghi %s từ Edge %s", entity_key, edge.pk)
        return _result_with_type(entity_key, RETRY, record["entity_type"],
                                 detail=str(exc)[:300])


def _result_with_type(entity_key, state, entity_type, detail=""):
    """Kết quả lỗi vẫn phải kèm `entity_type`.

    Tài liệu và lượt ứng tuyển dùng chung `entity_key`; thiếu `entity_type` thì
    Edge không biết kết quả này ứng với hàng nào trong hàng đợi, và hai loại ghi
    đè kết quả của nhau — đúng quy tắc `docs/SYNC.md` mục 7 đặt ra.
    """
    row = {"entity_key": entity_key, "entity_type": entity_type, "status": state}
    if detail:
        row["detail"] = detail
    return row


def _result(entity_key, state, pk, entity_type=ENTITY_SOURCE_RECORD):
    # entity_type đi kèm trong kết quả vì tài liệu và lượt ứng tuyển DÙNG CHUNG
    # entity_key. Thiếu nó thì Edge không biết kết quả này ứng với hàng nào trong
    # hàng đợi của mình, và hai loại sẽ ghi đè kết quả của nhau.
    return {"entity_key": entity_key, "entity_type": entity_type,
            "status": state, "id": str(pk)}
