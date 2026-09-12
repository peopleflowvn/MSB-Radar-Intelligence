# -*- coding: utf-8 -*-
"""API luồng nhập liệu ứng viên (Excel/CSV + nhiều CV) cho giao diện Hub.

Xác thực bằng phiên đăng nhập; quyền theo module `people_intake` (Admin gán cho
vai trò nào trong trang Quản trị → Phân quyền Module theo Vai trò). Không có
endpoint nào ở đây chạy AI hay ghi `SourceRecord` đồng bộ ngoài `commit/` — và
`commit/` gom lỗi theo từng dòng, không bao giờ 500 cả lô.
"""
import hashlib
import io
import logging
import os
from django.conf import settings

from accounts.permissions import RequiresPeopleIntake
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import (api_view, parser_classes,
                                       permission_classes)
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import export as export_mod
from . import fields as fields_mod
from . import ingest as ingest_mod
from .extract import extract_candidate
from .models import ImportBatch, ImportRow
from .parsing import ImportFileError, read_table
from .serializers import ImportBatchSerializer, ImportRowSerializer

log = logging.getLogger(__name__)

MAX_CV_FILES = 200
CV_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}


def _quiet_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        log.warning("Không xoá được file CV tạm %s", path)


def _stage_cv(batch_id, ext, data):
    """Lưu CV chờ duyệt vào vùng staging bền vững qua các lần restart."""
    staging = str(getattr(settings, "INTAKE_STAGING_ROOT", "") or "").strip()
    if not staging:
        staging = os.path.join(str(settings.BASE_DIR), "var", "intake-staging")
    os.makedirs(staging, exist_ok=True)
    filename = f"b{batch_id}_{hashlib.sha256(data).hexdigest()}{ext or '.bin'}"
    path = os.path.join(staging, filename)
    with open(path, "wb") as out:
        out.write(data)
    return path


# ── Template ───────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([RequiresPeopleIntake])
def download_template(request):
    """Tệp .xlsx mẫu: một sheet dữ liệu + một sheet hướng dẫn."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Ứng viên"
    headers = fields_mod.template_headers()
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.append(["Nguyễn Văn A", "a.nguyen@example.com", "0901234567",
               "Chuyên viên Phân tích Dữ liệu"])

    guide = wb.create_sheet("Hướng dẫn")
    guide.append(["Cột", "Ý nghĩa"])
    for col in fields_mod.COLUMNS:
        note = "Bắt buộc một trong Email/SĐT/LinkedIn." if col.key in fields_mod.IDENTITY_KEYS else ""
        if col.sensitive:
            note = (note + " Dữ liệu nhạy cảm.").strip()
        guide.append([col.header, note or "—"])

    buffer = io.BytesIO()
    wb.save(buffer)
    resp = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="radar_nhap_ung_vien.xlsx"'
    return resp


@api_view(["GET"])
@permission_classes([RequiresPeopleIntake])
def export_candidates(request):
    """CSV toàn kho, đúng cột `download_template` — chiều XUẤT của cùng template.

    Liên hệ (email/điện thoại) luôn bị che, không có tham số nào bật lại bản
    thô — xuất file là lúc dữ liệu rời khỏi hệ thống (xem `intake/export.py`).
    """
    return export_mod.export_candidates()


# ── Batch ──────────────────────────────────────────────────────────────────

@api_view(["GET", "POST"])
@permission_classes([RequiresPeopleIntake])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def batch_collection(request):
    if request.method == "GET":
        batches = ImportBatch.objects.all()[:50]
        return Response({"results": ImportBatchSerializer(batches, many=True).data})

    kind = request.data.get("kind") or ImportBatch.KIND_EXCEL
    if kind not in dict(ImportBatch.KIND_CHOICES):
        return Response({"detail": "Loại lô không hợp lệ."},
                        status=status.HTTP_400_BAD_REQUEST)
    source_label = str(request.data.get("source_label") or "").strip()[:40]

    if kind == ImportBatch.KIND_EXCEL:
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Chưa chọn tệp."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            _headers, rows = read_table(upload)
        except ImportFileError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        batch = ImportBatch.objects.create(
            created_by=request.user, kind=kind, source_label=source_label,
            original_filename=str(getattr(upload, "name", ""))[:300])
        _ingest_rows(batch, rows, source_label)
    else:
        batch = ImportBatch.objects.create(
            created_by=request.user, kind=kind, source_label=source_label,
            original_filename="")

    batch.recount()
    return Response(_batch_payload(batch), status=status.HTTP_201_CREATED)


@api_view(["GET", "DELETE"])
@permission_classes([RequiresPeopleIntake])
def batch_detail(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    if request.method == "DELETE":
        ingest_mod.cleanup_batch_files(batch)
        batch.delete()
        return Response({"ok": True})
    return Response(_batch_payload(batch))


@api_view(["PATCH"])
@permission_classes([RequiresPeopleIntake])
def row_detail(request, batch_id, row_id):
    row = get_object_or_404(ImportRow, pk=row_id, batch_id=batch_id)
    if row.validation_status == ImportRow.STATUS_COMMITTED:
        return Response({"detail": "Dòng đã ghi, không sửa được."},
                        status=status.HTTP_409_CONFLICT)

    if request.data.get("skip") is True:
        row.validation_status = ImportRow.STATUS_SKIPPED
        row.save(update_fields=["validation_status", "updated_at"])
        row.batch.recount()
        return Response(ImportRowSerializer(row).data)

    overrides = request.data.get("fields")
    if isinstance(overrides, dict):
        merged = {**(row.fields or {}), **{k: v for k, v in overrides.items()}}
        _revalidate_row(row, fields_mod.raw_from_fields(merged), row.batch.source_label)
        row.batch.recount()
    return Response(ImportRowSerializer(row).data)


# ── CV upload ──────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([RequiresPeopleIntake])
@parser_classes([MultiPartParser, FormParser])
def batch_cvs(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    if batch.status not in (ImportBatch.STATUS_DRAFT,):
        return Response({"detail": "Lô đã ghi, không thêm CV được."},
                        status=status.HTTP_409_CONFLICT)

    uploads = request.FILES.getlist("files")
    if not uploads:
        return Response({"detail": "Chưa chọn tệp CV."},
                        status=status.HTTP_400_BAD_REQUEST)
    if len(uploads) > MAX_CV_FILES:
        return Response({"detail": f"Tối đa {MAX_CV_FILES} CV mỗi lần."},
                        status=status.HTTP_400_BAD_REQUEST)

    attached, parsed, errors = 0, 0, []
    for upload in uploads:
        name = os.path.basename(str(getattr(upload, "name", "") or ""))
        ext = os.path.splitext(name)[1].lower()
        try:
            upload.seek(0)
            data = upload.read()
            digest = hashlib.sha256(data).hexdigest()
            path = _stage_cv(batch.pk, ext, data)

            if batch.kind == ImportBatch.KIND_EXCEL:
                row = _match_row_for_cv(batch, name)
                if row is None:
                    errors.append({"file": name, "error": "Không khớp dòng nào."})
                    os.remove(path)
                    continue
                row.cv_filename, row.cv_sha256, row.cv_tmp_path = name, digest, path
                row.save(update_fields=["cv_filename", "cv_sha256", "cv_tmp_path",
                                        "updated_at"])
                attached += 1
            else:
                row = _row_from_cv(batch, upload, name, digest, path, ext, errors)
                if row is not None:
                    parsed += 1
        except Exception as exc:                       # noqa: BLE001
            log.exception("Xử lý CV %s thất bại", name)
            errors.append({"file": name, "error": str(exc)[:200]})

    batch.recount()
    payload = _batch_payload(batch)
    payload["cv_result"] = {"attached": attached, "parsed": parsed, "errors": errors}
    return Response(payload)


# ── Commit ─────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([RequiresPeopleIntake])
def batch_commit(request, batch_id):
    batch = get_object_or_404(ImportBatch, pk=batch_id)
    if batch.status == ImportBatch.STATUS_DONE:
        return Response({"detail": "Lô đã được ghi."},
                        status=status.HTTP_409_CONFLICT)
    dedup_strategy = request.data.get("dedup_strategy") or "skip"
    if dedup_strategy not in ("skip", "update"):
        return Response({"detail": "dedup_strategy phải là skip hoặc update."},
                        status=status.HTTP_400_BAD_REQUEST)

    result = ingest_mod.commit_batch(batch, dedup_strategy=dedup_strategy,
                                     actor=request.user)
    ingest_mod.cleanup_batch_files(batch)
    payload = _batch_payload(batch)
    payload["commit_result"] = result
    return Response(payload)


# ── Helpers ────────────────────────────────────────────────────────────────

def _batch_payload(batch):
    return ImportBatchSerializer(batch, context={"with_rows": True}).data


def _ingest_rows(batch, rows, source_label):
    seen = set()
    to_create = []
    for index, raw in enumerate(rows):
        norm_fields, errors = fields_mod.normalize_row(raw)
        verdict = ingest_mod.evaluate_row(
            norm_fields, errors, source_label=source_label, seen_identities=seen)
        to_create.append(ImportRow(
            batch=batch, row_number=index + 2, raw=raw, fields=norm_fields,
            entity_key=verdict["entity_key"],
            validation_status=verdict["validation_status"],
            errors=verdict["errors"], matched_person=verdict["matched_person"]))
    ImportRow.objects.bulk_create(to_create)


def _revalidate_row(row, raw, source_label):
    norm_fields, errors = fields_mod.normalize_row(raw)
    verdict = ingest_mod.evaluate_row(norm_fields, errors, source_label=source_label,
                                      seen_identities=None)
    row.fields = norm_fields
    row.entity_key = verdict["entity_key"]
    row.validation_status = verdict["validation_status"]
    row.errors = verdict["errors"]
    row.matched_person = verdict["matched_person"]
    row.save(update_fields=["fields", "entity_key", "validation_status", "errors",
                            "matched_person", "updated_at"])


def _match_row_for_cv(batch, filename):
    """Ghép một file CV với dòng Excel: ưu tiên cột 'Tên file CV', rồi email/tên."""
    low = filename.strip().lower()
    stem = os.path.splitext(low)[0].replace(" ", "")
    candidates = list(batch.rows.filter(cv_sha256=""))

    for row in candidates:
        want = str((row.fields or {}).get("cv_file_name") or "").strip().lower()
        if want and (want == low or os.path.splitext(want)[0].replace(" ", "") == stem):
            return row
    for row in candidates:
        email_local = str((row.fields or {}).get("email") or "").split("@")[0].lower()
        name_key = str((row.fields or {}).get("fullname") or "").lower().replace(" ", "")
        if (email_local and email_local in stem) or (name_key and name_key in stem):
            return row
    return None


def _row_from_cv(batch, upload, name, digest, path, ext, errors):
    from talent.attachment_text import AttachmentError, extract_file

    if ext not in CV_EXTENSIONS:
        errors.append({"file": name, "error": f"Không hỗ trợ {ext or '(không đuôi)'}."})
        _quiet_remove(path)
        return None
    try:
        upload.seek(0)
        text = extract_file(upload)
    except AttachmentError as exc:
        errors.append({"file": name, "error": str(exc)[:200]})
        _quiet_remove(path)
        return None

    try:
        extracted = extract_candidate(text, filename=name)
    except Exception as exc:                            # noqa: BLE001
        log.warning("AI bóc CV %s lỗi: %s", name, exc)
        errors.append({"file": name, "error": "AI không bóc tách được: " + str(exc)[:150]})
        extracted = {}

    norm_fields, field_errors = fields_mod.normalize_row(
        fields_mod.raw_from_fields(extracted))
    row_number = (batch.rows.count() or 0) + 2
    row = ImportRow(batch=batch, row_number=row_number, raw={"_cv": name},
                    fields=norm_fields, cv_filename=name, cv_sha256=digest,
                    cv_tmp_path=path, ai_extracted=True)
    verdict = ingest_mod.evaluate_row(norm_fields, field_errors,
                                      source_label=batch.source_label,
                                      seen_identities=None)
    row.entity_key = verdict["entity_key"]
    row.validation_status = verdict["validation_status"]
    row.errors = verdict["errors"]
    row.matched_person = verdict["matched_person"]
    if not extracted:
        row.errors = {**row.errors, "ai": "AI không trả được trường nào; hãy sửa tay."}
    row.save()
    return row
