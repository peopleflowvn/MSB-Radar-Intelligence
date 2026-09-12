# -*- coding: utf-8 -*-
"""Kiểm thử tính năng Sao lưu CSDL lên Cloudflare R2 / Local Storage."""
from accounts import roles
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.backup_service import cleanup_old_backups, run_database_backup
from core.models import DatabaseBackupLog
from core.storage import reset_storage


class DatabaseBackupTest(TestCase):
    def setUp(self):
        roles.ensure_groups()
        self.admin = User.objects.create_user("admin_user", email="admin@example.com", password="password-1")
        self.admin.groups.add(Group.objects.get(name=roles.ADMIN))

        self.regular_user = User.objects.create_user("regular_user", email="user@example.com", password="password-2")
        self.regular_user.groups.add(Group.objects.get(name=roles.RECRUITER))

        reset_storage()

    def test_run_database_backup_creates_log_and_file(self):
        record = run_database_backup(trigger_type=DatabaseBackupLog.TRIGGER_MANUAL, user=self.admin)
        self.assertEqual(record.status, DatabaseBackupLog.STATUS_COMPLETED)
        self.assertTrue(record.filename.startswith("radar_db_backup_"))
        self.assertGreater(record.size_bytes, 0)
        self.assertTrue(record.sha256)
        self.assertEqual(record.created_by, self.admin)
        self.assertTrue(DatabaseBackupLog.objects.filter(pk=record.pk).exists())

    def test_admin_can_list_backups_and_get_summary(self):
        run_database_backup(trigger_type=DatabaseBackupLog.TRIGGER_SCHEDULED)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("core-backups-list"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("summary", data)
        self.assertIn("results", data)
        self.assertGreaterEqual(data["summary"]["total_backups"], 1)
        self.assertEqual(data["results"][0]["trigger_type"], DatabaseBackupLog.TRIGGER_SCHEDULED)

    def test_admin_can_trigger_backup_via_api(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("core-backups-trigger"))
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], DatabaseBackupLog.STATUS_COMPLETED)
        self.assertEqual(data["created_by"], "admin_user")

    def test_admin_can_download_and_delete_backup(self):
        record = run_database_backup(trigger_type=DatabaseBackupLog.TRIGGER_MANUAL, user=self.admin)
        self.client.force_login(self.admin)

        # Download
        response = self.client.get(reverse("core-backups-download", args=[record.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/gzip")
        self.assertIn(record.filename, response["Content-Disposition"])

        # Delete
        del_resp = self.client.delete(reverse("core-backups-delete", args=[record.pk]))
        self.assertEqual(del_resp.status_code, 200)
        self.assertFalse(DatabaseBackupLog.objects.filter(pk=record.pk).exists())

    def test_non_admin_cannot_access_backup_endpoints(self):
        self.client.force_login(self.regular_user)
        list_resp = self.client.get(reverse("core-backups-list"))
        self.assertEqual(list_resp.status_code, 403)

        trig_resp = self.client.post(reverse("core-backups-trigger"))
        self.assertEqual(trig_resp.status_code, 403)

    def test_cleanup_old_backups(self):
        # Tạo 3 bản ghi
        for _ in range(3):
            run_database_backup()
        # cleanup với retention_days=0 không xoá gì
        deleted = cleanup_old_backups(retention_days=0)
        self.assertEqual(deleted, 0)
