# -*- coding: utf-8 -*-
"""Tạo bản xem trước an toàn cho Kho CV.

File gốc không bao giờ được nhúng trực tiếp nếu đó là định dạng Office hoặc MIME
không tin cậy. Hub chỉ phát inline PDF/ảnh; Office được LibreOffice chuyển sang
PDF trong thư mục tạm rồi lưu riêng theo hash của file gốc.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .storage import get_storage

SAFE_INLINE_MIMES = {"application/pdf", "image/png", "image/jpeg", "image/webp", "text/plain"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".ods",
                     ".ppt", ".pptx", ".odp"}


def is_safe_inline(document):
    return (document.mime_type or "").lower() in SAFE_INLINE_MIMES


def preview_key(document):
    return f"previews/{document.sha256[:2]}/{document.sha256}.pdf"


def prepare_preview(document):
    """Đảm bảo Document có preview an toàn; lỗi được lưu để worker retry."""
    if not document.storage_key:
        return document
    if is_safe_inline(document):
        document.preview_key = document.storage_key
        document.preview_status = document.PARSE_DONE
        document.preview_error = ""
        document.previewed_at = timezone.now()
        document.save(update_fields=["preview_key", "preview_status", "preview_error",
                                     "previewed_at", "updated_at"])
        return document
    if document.preview_key and get_storage().exists(document.preview_key):
        return document

    extension = Path(document.filename or "").suffix.lower()
    if extension not in OFFICE_EXTENSIONS:
        _fail(document, "Định dạng này không được phép xem trực tiếp; hãy tải file gốc.")
        return document
    try:
        binary = get_storage().read(document.storage_key)
        with tempfile.TemporaryDirectory(prefix="msb-cv-preview-") as root:
            source = Path(root) / ("source" + extension)
            output = Path(root) / "out"
            profile = Path(root) / "profile"
            output.mkdir()
            source.write_bytes(binary)
            executable = _office_command()
            command = [executable, "--headless", f"-env:UserInstallation=file:///{profile.as_posix()}",
                       "--convert-to", "pdf", "--outdir", str(output), str(source)]
            subprocess.run(command, check=True, capture_output=True, timeout=90)
            rendered = output / "source.pdf"
            if not rendered.is_file() or rendered.stat().st_size == 0:
                raise RuntimeError("LibreOffice không tạo được bản PDF xem trước.")
            key = preview_key(document)
            get_storage().save(key, rendered.read_bytes())
        document.preview_key = key
        document.preview_status = document.PARSE_DONE
        document.preview_error = ""
        document.previewed_at = timezone.now()
        document.save(update_fields=["preview_key", "preview_status", "preview_error",
                                     "previewed_at", "updated_at"])
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        _fail(document, str(exc))
    return document


def _fail(document, message):
    document.preview_status = document.PARSE_FAILED
    document.preview_error = str(message)[:500]
    document.previewed_at = timezone.now()
    document.save(update_fields=["preview_status", "preview_error", "previewed_at", "updated_at"])


def _office_command():
    configured = getattr(settings, "OFFICE_PREVIEW_COMMAND", "soffice")
    if configured != "soffice" or shutil.which(configured):
        return configured
    # Cài đặt mặc định của LibreOffice trên Windows không luôn nằm trong PATH.
    for candidate in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                      r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if Path(candidate).is_file():
            return candidate
    return configured
