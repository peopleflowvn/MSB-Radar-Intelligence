# -*- coding: utf-8 -*-
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts import roles

from .models import KnowledgeDocument


class KnowledgeDocumentModelTest(TestCase):
    def test_radar_entity_id_is_negative_pk(self):
        document = KnowledgeDocument.objects.create(title="Quy trinh nghi phep")
        self.assertEqual(document.radar_entity_id, -document.pk)

    def test_radar_entity_id_requires_a_saved_row(self):
        document = KnowledgeDocument(title="chua luu")
        with self.assertRaises(ValueError):
            _ = document.radar_entity_id

    def test_store_file_fills_content_addressed_fields(self):
        document = KnowledgeDocument.objects.create(title="Chinh sach")
        document.store_file(b"noi dung file", filename="chinh-sach.txt")
        self.assertEqual(len(document.sha256), 64)
        self.assertTrue(document.storage_key.endswith(".txt"))
        self.assertEqual(document.file_size, len(b"noi dung file"))


class KnowledgeModuleAccessTest(TestCase):
    def setUp(self):
        roles.ensure_groups()
        self.user = get_user_model().objects.create_user("recruiter1", password="x")

    def test_recruiter_has_knowledge_module_by_default(self):
        """Recruiter là người hỏi Radar các câu chính sách/quy trình tuyển
        dụng nhiều nhất — thiếu quyền này khiến Radar luôn rơi vào tra web dù
        tài liệu nội bộ đã có sẵn (sửa 16/09, xem `accounts/roles.py`)."""
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.assertTrue(roles.can_access(self.user, roles.MODULE_KNOWLEDGE))

    def test_hiring_manager_does_not_have_knowledge_module_by_default(self):
        self.user.groups.add(Group.objects.get(name=roles.HIRING_MANAGER))
        self.assertFalse(roles.can_access(self.user, roles.MODULE_KNOWLEDGE))

    def test_admin_has_knowledge_module_by_default(self):
        self.user.groups.add(Group.objects.get(name=roles.ADMIN))
        self.assertTrue(roles.can_access(self.user, roles.MODULE_KNOWLEDGE))

    def test_admin_can_grant_knowledge_to_another_role_via_override(self):
        from accounts.models import RoleModuleAccess

        self.user.groups.add(Group.objects.get(name=roles.HIRING_MANAGER))
        RoleModuleAccess.objects.create(
            role=roles.HIRING_MANAGER, module=roles.MODULE_KNOWLEDGE, allowed=True)
        self.assertTrue(roles.can_access(self.user, roles.MODULE_KNOWLEDGE))


class KnowledgeAdminUploadTest(TestCase):
    """Tải file lên trang quản trị và Radar tự trích nội dung."""

    def setUp(self):
        roles.ensure_groups()
        self.admin = get_user_model().objects.create_superuser(
            "kb-super", "kb@example.test", "secret")
        self.client.force_login(self.admin)

    def _post(self, **extra):
        payload = {"title": "Quy trinh nghi phep", "category": "hr_policy",
                   "parsed_text": "", "is_active": "on"}
        payload.update(extra)
        return self.client.post(
            reverse("admin:knowledge_knowledgedocument_add"), payload, follow=True)

    def test_uploaded_text_file_is_extracted_without_manual_paste(self):
        upload = SimpleUploadedFile(
            "chinh-sach.txt", "Nhan vien duoc nghi 12 ngay phep nam.".encode("utf-8"),
            content_type="text/plain")
        response = self._post(upload=upload)
        self.assertEqual(response.status_code, 200)
        document = KnowledgeDocument.objects.get()
        self.assertIn("12 ngay phep", document.parsed_text)
        self.assertEqual(document.parse_status, KnowledgeDocument.PARSE_DONE)
        self.assertEqual(document.uploaded_by, self.admin)
        self.assertTrue(document.storage_key)

    def test_manual_text_is_never_overwritten_by_the_extractor(self):
        upload = SimpleUploadedFile(
            "chinh-sach.txt", "noi dung trong file".encode("utf-8"), content_type="text/plain")
        self._post(upload=upload, parsed_text="noi dung nhap tay")
        document = KnowledgeDocument.objects.get()
        self.assertEqual(document.parsed_text, "noi dung nhap tay")

    def test_unreadable_upload_still_saves_and_warns(self):
        upload = SimpleUploadedFile(
            "anh.bin", b"\x00\x01\x02", content_type="application/octet-stream")
        response = self._post(upload=upload)
        document = KnowledgeDocument.objects.get()
        self.assertEqual(document.parse_status, KnowledgeDocument.PARSE_FAILED)
        self.assertContains(response, "Chưa trích được nội dung")

    def test_document_without_upload_still_works(self):
        self._post(parsed_text="chinh sach nhap tay")
        document = KnowledgeDocument.objects.get()
        self.assertEqual(document.parsed_text, "chinh sach nhap tay")
        self.assertEqual(document.storage_key, "")
