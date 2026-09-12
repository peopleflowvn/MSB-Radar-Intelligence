# -*- coding: utf-8 -*-
"""Đưa các dòng của một `ImportBatch` vào bàn nhận `SourceRecord`.

Đây là chỗ luồng nhập liệu thủ công nối vào "bộ não" của Radar. Không có đường
tắt: mỗi dòng trở thành một `SourceRecord` dưới một Edge dành riêng
(`hub-manual`), rồi đi qua đúng `people.ingest.resolve_record` (phân giải Person,
hàng chờ xung đột, không tự gộp) và `talent.derive` như dữ liệu Edge.

Nhờ vậy dữ liệu nhập tay thừa hưởng nguyên các bảo đảm của Master Plan:
§2.2 raw bất biến, §2.3 con người thắng máy (curated không bị ghi đè),
§2.4 AI/không-ai tự gộp định danh, §5 provenance qua `source_kind`.
"""
import logging
import os
import re

from core.ingest import upsert_source_record
from core.models import Edge
from core.serializers import (ENTITY_SOURCE_RECORD, content_hash,
                              promote_columns)

from . import fields as fields_mod
from .dedupe import match_person, primary_identity
from .models import ImportBatch, ImportRow

log = logging.getLogger(__name__)

MANUAL_EDGE_ID = "hub-manual"
MANUAL_EDGE_LABEL = "Nhập liệu thủ công (Hub)"

_SOURCE_KIND = {
    ImportBatch.KIND_EXCEL: "import",
    ImportBatch.KIND_BULK_CV: "bulk_cv",
}

_MIME_BY_EXT = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
}


def manual_edge():
    """Edge ảo dùng chung cho mọi luồng nhập liệu thủ công.

    Một hàng `Edge` thật để khoá duy nhất `(edge, entity_type, entity_key)` của
    bàn nhận vẫn áp dụng, và để giao diện Vận hành Edge nhìn thấy nguồn này như
    một nguồn nạp dữ liệu bình thường.
    """
    edge, _created = Edge.objects.get_or_create(
        edge_id=MANUAL_EDGE_ID,
        defaults={"label": MANUAL_EDGE_LABEL, "is_active": True})
    return edge


# ── Validate một dòng ────────────────────────────────────────────────────────

def evaluate_row(fields, errors, *, source_label, seen_identities=None):
    """Xét một dòng đã chuẩn hoá. Trả dict cập nhật được cho `ImportRow`.

    `seen_identities`: set các định danh đã gặp ở những dòng TRƯỚC trong cùng tệp
    (để bắt trùng nội bộ). Truyền `None` khi validate lại một dòng lẻ.
    """
    errors = dict(errors or {})
    ident = primary_identity(fields)
    entity_key = ""
    matched, matched_name, conflict = None, "", False

    if not ident:
        errors.setdefault(
            "identity", "Cần ít nhất Email, Số điện thoại hoặc LinkedIn để định danh.")
        status = ImportRow.STATUS_INVALID
    else:
        entity_key = compute_entity_key(source_label, ident)
        if seen_identities is not None and ident in seen_identities:
            errors.setdefault("duplicate", "Trùng với một dòng khác trong cùng tệp.")
            status = ImportRow.STATUS_DUPLICATE
        else:
            person, conflict = match_person(fields)
            if person is not None:
                matched, matched_name = person, person.display_name
                errors.setdefault(
                    "duplicate",
                    "Đã có người này trong hệ thống."
                    + (" (định danh trỏ nhiều người — sẽ tạo phiếu xung đột)"
                       if conflict else ""))
                status = ImportRow.STATUS_DUPLICATE
            elif errors:
                status = ImportRow.STATUS_INVALID
            else:
                status = ImportRow.STATUS_VALID

    if seen_identities is not None and ident:
        seen_identities.add(ident)

    return {
        "entity_key": entity_key,
        "validation_status": status,
        "errors": errors,
        "matched_person": matched,
        "_matched_name": matched_name,
        "_conflict": conflict,
    }


def compute_entity_key(source_label, ident):
    slug = re.sub(r"[^a-z0-9]+", "-", str(source_label or "").lower()).strip("-")
    return f"intake|{slug or 'thu-cong'}|{ident}"


# ── Build payload cho bàn nhận ──────────────────────────────────────────────

def build_payload(row, batch):
    """`ImportRow.fields` → payload `SourceRecord` (cùng từ vựng với payload Edge).

    Chỉ trường nghiệp vụ + `source` + `source_kind`. KHÔNG kèm id lô / người nhập —
    những thứ đó làm `content_hash` đổi theo lô và phá tính idempotent.
    """
    payload = {k: v for k, v in (row.fields or {}).items()
               if k in fields_mod.PAYLOAD_KEYS}
    payload["source"] = (row.fields or {}).get("source") or batch.source_label or "thu_cong"
    payload["source_kind"] = _SOURCE_KIND.get(batch.kind, "import")
    return {k: ("" if v is None else v) for k, v in payload.items()}


# ── Commit ──────────────────────────────────────────────────────────────────

def commit_batch(batch, *, dedup_strategy="skip", actor=None):
    """Ghi các dòng đủ điều kiện của `batch` vào bàn nhận rồi phân giải Person.

    `dedup_strategy`:
      - `skip`   — dòng `duplicate` bị bỏ qua (không đụng hồ sơ đã có).
      - `update` — dòng `duplicate` vẫn ghi; bàn nhận cập nhật bản ghi cũ và
        `talent.derive` chạy lại (curated vẫn được bảo vệ).

    Gom lỗi theo từng dòng; một dòng hỏng KHÔNG làm dừng cả lô.
    """
    from people.ingest import resolve_record

    edge = manual_edge()
    batch.status = ImportBatch.STATUS_COMMITTING
    batch.save(update_fields=["status", "updated_at"])

    committed = 0
    for row in batch.rows.select_related("batch").all():
        if not row.eligible_for_commit:
            continue
        if row.validation_status == ImportRow.STATUS_DUPLICATE and dedup_strategy == "skip":
            row.validation_status = ImportRow.STATUS_SKIPPED
            row.save(update_fields=["validation_status", "updated_at"])
            continue

        payload = build_payload(row, batch)
        try:
            record, _outcome = upsert_source_record(
                edge,
                entity_type=ENTITY_SOURCE_RECORD,
                entity_key=row.entity_key,
                payload=payload,
                content_hash=content_hash(payload),
                columns=promote_columns(payload))
        except Exception as exc:                        # noqa: BLE001
            log.exception("Commit dòng %s lô %s thất bại", row.pk, batch.pk)
            row.validation_status = ImportRow.STATUS_ERROR
            row.errors = {**(row.errors or {}), "commit": str(exc)[:300]}
            row.save(update_fields=["validation_status", "errors", "updated_at"])
            continue

        row.source_record = record

        # Phân giải Person + dựng TalentProfile — đúng đường Edge đi.
        try:
            resolve_record(record)
        except Exception:                              # noqa: BLE001
            log.exception("Phân giải bản ghi %s (dòng nhập liệu) thất bại", record.pk)
        record.refresh_from_db(fields=["person"])

        cv_error = _attach_cv(row, record) if row.cv_sha256 else ""
        if cv_error:
            row.errors = {**(row.errors or {}), "cv": cv_error}

        row.validation_status = ImportRow.STATUS_COMMITTED
        row.save(update_fields=["source_record", "validation_status", "errors",
                                "updated_at"])
        committed += 1
        _log_interaction(record, batch, actor)

    batch.status = ImportBatch.STATUS_DONE
    batch.save(update_fields=["status", "updated_at"])
    batch.recount()
    return {"committed": committed}


def _attach_cv(row, record):
    """Đính CV tạm của một dòng vào Person qua đường tài liệu 2 pha sẵn có.

    Trả chuỗi lỗi (rỗng nếu ổn). Parsing do worker Hub lo — không chạy ở đây.
    """
    from core.documents import DocumentError, ingest_metadata, store_file

    if record.person is None:
        return "Chưa phân giải được Person nên chưa gắn được CV."
    if not row.cv_tmp_path or not os.path.exists(row.cv_tmp_path):
        return "Không tìm thấy file CV tạm."

    ext = (row.cv_filename.rsplit(".", 1)[-1] if "." in row.cv_filename else "").lower()
    meta = {
        "sha256": row.cv_sha256,
        "filename": row.cv_filename,
        "document_type": "cv",
        "mime_type": _MIME_BY_EXT.get(ext, ""),
        "observed_at": (row.fields or {}).get("applied_at") or "",
        "source": (row.fields or {}).get("source") or "",
    }
    try:
        with open(row.cv_tmp_path, "rb") as fh:
            data = fh.read()
        _document, needs_file = ingest_metadata(record, meta)
        if needs_file:
            store_file(record.person, row.cv_sha256, data, filename=row.cv_filename)
    except DocumentError as exc:
        return str(exc)[:300]
    except Exception as exc:                            # noqa: BLE001
        log.exception("Gắn CV cho dòng %s thất bại", row.pk)
        return str(exc)[:300]
    return ""


def _log_interaction(record, batch, actor):
    try:
        from people.models import Interaction
        if record.person is None:
            return
        Interaction.objects.create(
            person=record.person, domain="talent",
            action="intake_import", actor=actor,
            detail={"batch_id": batch.pk, "kind": batch.kind,
                    "source": (record.payload or {}).get("source", "")})
    except Exception:                                  # noqa: BLE001
        log.exception("Không ghi được Interaction cho commit nhập liệu")


def cleanup_batch_files(batch):
    """Xoá file CV tạm của một lô (khi huỷ nháp hoặc sau khi commit xong)."""
    for row in batch.rows.exclude(cv_tmp_path="").only("cv_tmp_path"):
        try:
            if os.path.exists(row.cv_tmp_path):
                os.remove(row.cv_tmp_path)
        except OSError:
            log.warning("Không xoá được file tạm %s", row.cv_tmp_path)
