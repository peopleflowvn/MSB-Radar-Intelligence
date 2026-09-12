# -*- coding: utf-8 -*-
"""Dịch vụ sao lưu cơ sở dữ liệu PostgreSQL lên Cloudflare R2 / Local Storage."""
import gzip
import hashlib
import io
import logging
import os
import secrets
import subprocess
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from .models import DatabaseBackupLog
from .storage import get_storage

log = logging.getLogger(__name__)


def _generate_backup_data():
    """Tạo dữ liệu sao lưu nén gzip từ CSDL hiện tại.

    Ưu tiên pg_dump nếu là PostgreSQL và có binary pg_dump trong hệ thống;
    fallback sang Django serialized dumpdata (nén gzip) nếu chạy cục bộ/test.
    """
    db_config = settings.DATABASES.get("default", {})
    engine = db_config.get("ENGINE", "")
    db_name = db_config.get("NAME", "radar_db")
    db_user = db_config.get("USER", "")
    db_password = db_config.get("PASSWORD", "")
    db_host = db_config.get("HOST", "localhost")
    db_port = str(db_config.get("PORT", "5432") or "5432")

    if "postgresql" in engine:
        env = os.environ.copy()
        if db_password:
            env["PGPASSWORD"] = str(db_password)

        cmd = [
            "pg_dump",
            "-h", str(db_host or "localhost"),
            "-p", str(db_port or "5432"),
            "-U", str(db_user or "postgres"),
            "--no-owner",
            "--no-privileges",
            "-F", "c",  # PostgreSQL custom archive format (nhỏ gọn & khôi phục an toàn với pg_restore)
            str(db_name),
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            stdout_data, stderr_data = proc.communicate(timeout=600)
            if proc.returncode == 0 and stdout_data:
                # Custom format của pg_dump đã nén sẵn, bọc thêm gzip buffer để đồng nhất định dạng
                compressed = gzip.compress(stdout_data, compresslevel=6)
                return compressed, "sql.gz"
            log.warning("pg_dump thất bại (code %s): %s. Thử chuyển sang dumpdata.",
                        proc.returncode, stderr_data.decode("utf-8", errors="replace")[:300])
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
            log.info("Không gọi được pg_dump trực tiếp (%s). Dùng cơ chế Django dumpdata.", exc)

    # Fallback: Django dumpdata nén gzip (loại trừ contenttypes/sessions/auth events tạm)
    buf = io.StringIO()
    call_command("dumpdata", stdout=buf, format="json", indent=None,
                 exclude=["contenttypes", "sessions.Session"])
    json_bytes = buf.getvalue().encode("utf-8")
    compressed = gzip.compress(json_bytes, compresslevel=6)
    return compressed, "json.gz"


def run_database_backup(trigger_type=DatabaseBackupLog.TRIGGER_MANUAL, user=None, retention_days=30):
    """Thực hiện một lượt sao lưu CSDL hoàn chỉnh và lưu vào Cloudflare R2."""
    now = timezone.now()
    t0 = timezone.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    rand_suffix = secrets.token_hex(4)
    storage = get_storage()
    backend_name = getattr(storage, "name", "local")

    log_entry = DatabaseBackupLog.objects.create(
        filename=f"radar_db_backup_{stamp}_{rand_suffix}.pending",
        storage_key="",
        storage_backend=backend_name,
        status=DatabaseBackupLog.STATUS_IN_PROGRESS,
        trigger_type=trigger_type,
        created_by=user,
        created_at=now,
    )

    try:
        compressed_data, ext = _generate_backup_data()
        filename = f"radar_db_backup_{stamp}_{rand_suffix}.{ext}"
        storage_key = f"backups/db/{filename}"

        # Upload vào R2 / Filestore
        storage.save(storage_key, compressed_data)

        size_bytes = len(compressed_data)
        sha256_hash = hashlib.sha256(compressed_data).hexdigest()
        duration_ms = int((timezone.now() - t0).total_seconds() * 1000)

        log_entry.filename = filename
        log_entry.storage_key = storage_key
        log_entry.size_bytes = size_bytes
        log_entry.sha256 = sha256_hash
        log_entry.status = DatabaseBackupLog.STATUS_COMPLETED
        log_entry.duration_ms = duration_ms
        log_entry.save()

        # Dọn dẹp bản backup cũ quá thời hạn (Retention Policy)
        cleanup_old_backups(retention_days=retention_days)

        log.info("Sao lưu CSDL thành công: %s (%s bytes, %sms) -> %s",
                 filename, size_bytes, duration_ms, storage_key)
        return log_entry

    except Exception as exc:
        duration_ms = int((timezone.now() - t0).total_seconds() * 1000)
        log.exception("Sao lưu CSDL thất bại: %s", exc)
        log_entry.status = DatabaseBackupLog.STATUS_FAILED
        log_entry.error_message = str(exc)[:1000]
        log_entry.duration_ms = duration_ms
        log_entry.save(update_fields=["status", "error_message", "duration_ms", "updated_at"])
        raise


def cleanup_old_backups(retention_days=30, keep_min=10):
    """Tự động xoá các bản sao lưu cũ quá retention_days trên cả R2 và database."""
    if retention_days <= 0:
        return 0
    cutoff = timezone.now() - timedelta(days=retention_days)
    old_records = DatabaseBackupLog.objects.filter(
        status=DatabaseBackupLog.STATUS_COMPLETED,
        created_at__lt=cutoff
    ).order_by("created_at")

    # Giữ lại ít nhất `keep_min` bản ghi gần nhất để an toàn
    total_completed = DatabaseBackupLog.objects.filter(status=DatabaseBackupLog.STATUS_COMPLETED).count()
    deletable_count = max(0, total_completed - keep_min)
    to_delete = list(old_records[:deletable_count])

    deleted = 0
    storage = get_storage()
    for record in to_delete:
        try:
            if record.storage_key and storage.exists(record.storage_key):
                storage.delete(record.storage_key)
        except Exception as exc:
            log.warning("Không xoá được tệp backup trên storage: %s (%s)", record.storage_key, exc)
        record.delete()
        deleted += 1

    if deleted > 0:
        log.info("Đã dọn dẹp %s bản sao lưu CSDL cũ quá %s ngày.", deleted, retention_days)
    return deleted
