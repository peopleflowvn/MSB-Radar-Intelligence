# -*- coding: utf-8 -*-
"""Retention của reasoning_trace + audit xoá cứng hội thoại (Master Plan §21.5)."""
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import AccessLog
from .models import AssistantEvent, AssistantMessage, AssistantThread


def _age(obj, days):
    type(obj).objects.filter(pk=obj.pk).update(
        created_at=timezone.now() - timezone.timedelta(days=days))


class PruneReasoningTracesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("prune")
        self.thread = AssistantThread.objects.create(
            user=self.user, surface="talent", thread_id="t-prune")

    def test_removes_trace_from_old_messages_only(self):
        old = AssistantMessage.objects.create(
            thread=self.thread, role="assistant", content="cũ",
            metadata={"reasoning_trace": "suy luận nhạy cảm", "mode": "conversation"})
        recent = AssistantMessage.objects.create(
            thread=self.thread, role="assistant", content="mới",
            metadata={"reasoning_trace": "vẫn giữ", "mode": "conversation"})
        _age(old, 90)
        _age(recent, 5)

        out = StringIO()
        call_command("prune_reasoning_traces", "--days", "60", stdout=out)
        old.refresh_from_db()
        self.assertIn("reasoning_trace", old.metadata)   # dry-run: chưa đụng

        call_command("prune_reasoning_traces", "--days", "60", "--commit", stdout=out)
        old.refresh_from_db()
        recent.refresh_from_db()
        self.assertNotIn("reasoning_trace", old.metadata)
        self.assertTrue(old.metadata["reasoning_trace_pruned"])
        self.assertEqual(old.content, "cũ")              # message vẫn còn
        self.assertEqual(recent.metadata["reasoning_trace"], "vẫn giữ")

    def test_events_flag_prunes_model_requested_payload(self):
        event = AssistantEvent.objects.create(
            thread=self.thread, turn_id="turn-x", seq=1,
            kind=AssistantEvent.KIND_MODEL_REQUESTED,
            payload={"messages": [{"role": "user", "content": "bí mật"}],
                     "task": "assistant_conversation", "params": {"max_tokens": 600}})
        _age(event, 120)
        call_command("prune_reasoning_traces", "--days", "60", "--commit", "--events",
                     stdout=StringIO())
        event.refresh_from_db()
        self.assertIsNone(event.payload["messages"])
        self.assertTrue(event.payload["messages_pruned"])
        self.assertEqual(event.payload["params"]["max_tokens"], 600)


class PruneConversationsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("retain")

    def _thread(self, tid, *, archived, age_days):
        t = AssistantThread.objects.create(
            user=self.user, surface="talent", thread_id=tid, archived=archived)
        AssistantMessage.objects.create(thread=t, role="user", content="hỏi")
        AssistantThread.objects.filter(pk=t.pk).update(
            updated_at=timezone.now() - timezone.timedelta(days=age_days))
        return t

    def test_only_old_archived_threads_are_removed(self):
        old_archived = self._thread("old-arch", archived=True, age_days=400)
        old_active = self._thread("old-active", archived=False, age_days=400)
        recent_archived = self._thread("new-arch", archived=True, age_days=10)

        call_command("prune_conversations", "--days", "365", "--commit", stdout=StringIO())

        self.assertFalse(AssistantThread.objects.filter(pk=old_archived.pk).exists())
        self.assertTrue(AssistantThread.objects.filter(pk=old_active.pk).exists())
        self.assertTrue(AssistantThread.objects.filter(pk=recent_archived.pk).exists())

        row = AccessLog.objects.get(object_id="old-arch", action=AccessLog.ACTION_DELETE)
        self.assertEqual(row.extra["reason"], "retention")
        self.assertEqual(row.method, "JOB")

    def test_include_active_flag_widens_scope(self):
        self._thread("old-active-2", archived=False, age_days=400)
        call_command("prune_conversations", "--days", "365", "--commit",
                     "--include-active", stdout=StringIO())
        self.assertFalse(AssistantThread.objects.filter(thread_id="old-active-2").exists())

    def test_dry_run_touches_nothing(self):
        self._thread("keep-me", archived=True, age_days=400)
        call_command("prune_conversations", "--days", "365", stdout=StringIO())
        self.assertTrue(AssistantThread.objects.filter(thread_id="keep-me").exists())


class ConversationDeleteAuditTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="x")
        self.thread = AssistantThread.objects.create(
            user=self.user, surface="talent", thread_id="c-del", title="riêng")
        AssistantMessage.objects.create(
            thread=self.thread, role="assistant", content="x",
            metadata={"reasoning_trace": "abc"})
        AssistantEvent.objects.create(thread=self.thread, turn_id="t1", seq=1,
                                      kind=AssistantEvent.KIND_TURN_STARTED, payload={})

    def test_hard_delete_writes_access_log(self):
        self.client.force_authenticate(self.user)
        resp = self.client.delete("/api/v1/ai/conversations/c-del/?surface=talent")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(AssistantThread.objects.filter(pk=self.thread.pk).exists())

        row = AccessLog.objects.get(action=AccessLog.ACTION_DELETE,
                                    object_type="assistant_thread")
        self.assertEqual(row.object_id, "c-del")
        self.assertEqual(row.user, self.user)
        self.assertEqual(row.extra["surface"], "talent")
        self.assertEqual(row.extra["message_count"], 1)
        self.assertTrue(row.extra["had_reasoning_trace"])
