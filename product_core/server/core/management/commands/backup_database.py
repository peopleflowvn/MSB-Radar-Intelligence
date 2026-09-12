# -*- coding: utf-8 -*-
"""Command sao lưu cơ sở dữ liệu lên Cloudflare R2: python manage.py backup_database [--auto]."""
import sys
from django.core.management.base import BaseCommand

from core.backup_service import run_database_backup
from core.models import DatabaseBackupLog


class Command(BaseCommand):
    help = "Sao luu CSDL PostgreSQL len Cloudflare R2 / Local Storage theo lich trinh (2 lan/ngay) hoac thu cong."

    def add_arguments(self, parser):
        parser.add_argument(
            "--auto",
            action="store_true",
            help="Danh dau lan sao luu tu dong theo lich dinh ky.",
        )
        parser.add_argument(
            "--retention",
            type=int,
            default=30,
            help="So ngay luu tru toi da truoc khi tu dong don dep (mac dinh 30 ngay).",
        )

    def handle(self, *args, **options):
        is_auto = options.get("auto", False)
        retention = options.get("retention", 30)
        trigger_type = DatabaseBackupLog.TRIGGER_SCHEDULED if is_auto else DatabaseBackupLog.TRIGGER_MANUAL

        trigger_label = "Auto Scheduled (2x/day)" if is_auto else "Manual Admin"
        self.stdout.write(f"Starting Database Backup ({trigger_label}, Retention: {retention} days)...")

        try:
            log_entry = run_database_backup(trigger_type=trigger_type, retention_days=retention)
            size_mb = log_entry.size_bytes / (1024 * 1024)
            self.stdout.write(self.style.SUCCESS(
                f"[OK] Backup completed: {log_entry.filename} ({size_mb:.2f} MB, {log_entry.duration_ms}ms) -> {log_entry.storage_key}"
            ))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"[ERROR] Backup failed: {exc}"))
            sys.exit(1)
