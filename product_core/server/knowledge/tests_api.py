# -*- coding: utf-8 -*-
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts import roles

from .models import KnowledgeDocument


class KnowledgeApiPermissionTest(TestCase):
    def setUp(self):
        roles.ensure_groups()
        self.recruiter = get_user_model().objects.create_user("kb-api-recruiter", password="x")
        self.recruiter.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.admin = get_user_model().objects.create_user(
            "kb-api-admin", password="x", is_superuser=True)

    def test_recruiter_without_module_is_forbidden(self):
        self.client.force_login(self.recruiter)
        response = self.client.get(reverse("knowledge-documents"))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_unauthorized(self):
        response = self.client.get(reverse("knowledge-documents"))
        self.assertIn(response.status_code, (401, 403))


class KnowledgeApiCrudTest(TestCase):
    def setUp(self):
        roles.ensure_groups()
        self.admin = get_user_model().objects.create_user(
            "kb-api-admin2", password="x", is_superuser=True)
        self.client.force_login(self.admin)

    def test_list_is_empty_initially(self):
        response = self.client.get(reverse("knowledge-documents"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])
        self.assertTrue(response.json()["categories"])

    def test_create_with_manual_text(self):
        response = self.client.post(
            reverse("knowledge-documents"),
            {"title": "Quy trinh nghi phep", "category": "hr_policy",
             "parsed_text": "12 ngay phep nam"},
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["title"], "Quy trinh nghi phep")
        self.assertEqual(body["parsed_text"], "12 ngay phep nam")
        self.assertTrue(body["is_active"])

    def test_create_without_text_or_file_is_rejected(self):
        response = self.client.post(
            reverse("knowledge-documents"), {"title": "Trong rong"})
        self.assertEqual(response.status_code, 400)

    def test_upload_extracts_text_automatically(self):
        upload = SimpleUploadedFile(
            "chinh-sach.txt", "Nhan vien duoc nghi 12 ngay phep nam.".encode("utf-8"),
            content_type="text/plain")
        response = self.client.post(
            reverse("knowledge-documents-upload"),
            {"title": "Chinh sach nghi phep", "category": "hr_policy", "file": upload},
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertIn("12 ngay phep", body["parsed_text"])
        self.assertEqual(body["parse_status"], "done")
        self.assertNotIn("warning", body)

    def test_upload_without_file_is_rejected(self):
        response = self.client.post(
            reverse("knowledge-documents-upload"), {"title": "Khong co file"})
        self.assertEqual(response.status_code, 400)

    def test_patch_deactivate(self):
        document = KnowledgeDocument.objects.create(title="X", parsed_text="y")
        response = self.client.patch(
            reverse("knowledge-document-detail", args=[document.pk]),
            {"is_active": False}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])
        document.refresh_from_db()
        self.assertFalse(document.is_active)

    def test_delete_removes_the_document(self):
        document = KnowledgeDocument.objects.create(title="X", parsed_text="y")
        response = self.client.delete(
            reverse("knowledge-document-detail", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(KnowledgeDocument.objects.filter(pk=document.pk).exists())

    def test_filter_by_category(self):
        KnowledgeDocument.objects.create(
            title="A", category="hr_policy", parsed_text="a")
        KnowledgeDocument.objects.create(
            title="B", category="guideline", parsed_text="b")
        response = self.client.get(reverse("knowledge-documents"), {"category": "hr_policy"})
        titles = [row["title"] for row in response.json()["results"]]
        self.assertEqual(titles, ["A"])
