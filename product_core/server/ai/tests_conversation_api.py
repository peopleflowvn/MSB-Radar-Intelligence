# -*- coding: utf-8 -*-
"""API CRUD hội thoại: cách ly theo chủ sở hữu và theo surface (Master Plan §10.2, §16.3)."""
from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from .models import AssistantMessage, AssistantThread


class ConversationApiTest(APITestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="x")
        self.bob = User.objects.create_user("bob", password="x")

    def _thread(self, user, surface, thread_id, title=""):
        return AssistantThread.objects.create(
            user=user, surface=surface, thread_id=thread_id, title=title)

    # --- tạo & liệt kê ---------------------------------------------------------
    def test_create_and_list_scoped_to_surface_and_owner(self):
        self.client.force_authenticate(self.alice)
        resp = self.client.post("/api/v1/ai/conversations/",
                                {"surface": "talent", "title": "Tìm BA"}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.client.post("/api/v1/ai/conversations/",
                         {"surface": "prospect"}, format="json")

        talent = self.client.get("/api/v1/ai/conversations/?surface=talent").json()["results"]
        self.assertEqual(len(talent), 1)
        self.assertEqual(talent[0]["surface"], "talent")

        # Bob không thấy hội thoại của Alice.
        self.client.force_authenticate(self.bob)
        self.assertEqual(
            self.client.get("/api/v1/ai/conversations/?surface=talent").json()["results"], [])

    def test_invalid_surface_rejected(self):
        self.client.force_authenticate(self.alice)
        resp = self.client.post("/api/v1/ai/conversations/",
                                {"surface": "nonsense"}, format="json")
        self.assertEqual(resp.status_code, 400)

    # --- cách ly quyền -------------------------------------------------------
    def test_other_user_cannot_read_update_or_delete(self):
        row = self._thread(self.alice, "talent", "secret", title="riêng")
        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.get(f"/api/v1/ai/conversations/{row.thread_id}/").status_code, 404)
        self.assertEqual(self.client.patch(f"/api/v1/ai/conversations/{row.thread_id}/",
                                           {"title": "hijack"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/ai/conversations/{row.thread_id}/").status_code, 404)
        row.refresh_from_db()
        self.assertEqual(row.title, "riêng")

    def test_same_thread_id_different_surface_does_not_cross(self):
        talent = self._thread(self.alice, "talent", "dup", title="phía talent")
        prospect = self._thread(self.alice, "prospect", "dup", title="phía prospect")
        self.client.force_authenticate(self.alice)

        got = self.client.get("/api/v1/ai/conversations/dup/?surface=prospect").json()
        self.assertEqual(got["id"], prospect.id)
        self.assertEqual(got["surface"], "prospect")

        self.client.patch("/api/v1/ai/conversations/dup/",
                          {"surface": "talent", "archived": True}, format="json")
        talent.refresh_from_db()
        prospect.refresh_from_db()
        self.assertTrue(talent.archived)
        self.assertFalse(prospect.archived)

    def test_rename_archive_delete_happy_path(self):
        row = self._thread(self.alice, "talent", "t1")
        self.client.force_authenticate(self.alice)

        self.client.patch("/api/v1/ai/conversations/t1/", {"title": "  Tên  mới  "}, format="json")
        row.refresh_from_db()
        self.assertEqual(row.title, "Tên mới")

        # archive ẩn khỏi danh sách nhưng không xoá.
        self.client.patch("/api/v1/ai/conversations/t1/", {"archived": True}, format="json")
        self.assertEqual(
            self.client.get("/api/v1/ai/conversations/?surface=talent").json()["results"], [])
        self.assertTrue(AssistantThread.objects.filter(pk=row.pk).exists())

        self.assertEqual(self.client.delete("/api/v1/ai/conversations/t1/").status_code, 204)
        self.assertFalse(AssistantThread.objects.filter(pk=row.pk).exists())

    def test_detail_returns_messages_with_client_turn_id(self):
        row = self._thread(self.alice, "talent", "t2")
        AssistantMessage.objects.create(thread=row, role="user", content="hỏi",
                                        client_turn_id="turn-1")
        AssistantMessage.objects.create(thread=row, role="assistant", content="đáp")
        self.client.force_authenticate(self.alice)
        got = self.client.get("/api/v1/ai/conversations/t2/").json()
        self.assertEqual(len(got["messages"]), 2)
        self.assertEqual(got["messages"][0]["client_turn_id"], "turn-1")

    def test_requires_authentication(self):
        self.assertIn(self.client.get("/api/v1/ai/conversations/").status_code, (401, 403))
