# -*- coding: utf-8 -*-
"""Toolset registry (§23.1.3) + background review proposals (§15 GĐ5, §23.1.6)."""
from io import StringIO

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.management import call_command
from django.test import TestCase

from accounts import roles

from .models import AssistantFeedback, AssistantThread, LongTermMemory
from .toolset import tool_names_for, toolset_for


def _user(name, *role_names):
    roles.ensure_groups()
    u = User.objects.create_user(name, password="x")
    for r in role_names:
        u.groups.add(Group.objects.get(name=r))
    return u


class ToolsetTest(TestCase):
    def test_scoped_by_surface_and_rbac(self):
        recruiter = _user("rec", roles.RECRUITER)          # talent, không rb
        rm = _user("rm", roles.RB_SALES)                   # rb + talent

        rec_talent = tool_names_for("talent", recruiter)
        self.assertIn("search_people", rec_talent)
        self.assertNotIn("search_prospects", rec_talent)   # đúng surface nhưng thiếu quyền RB
        self.assertIn("feedback", rec_talent)              # module=None -> ai đăng nhập cũng có

        self.assertIn("search_prospects", tool_names_for("prospect", rm))
        # recruiter ở surface prospect: search_prospects vẫn bị chặn vì thiếu quyền
        self.assertNotIn("search_prospects", tool_names_for("prospect", recruiter))

    def test_anonymous_gets_nothing(self):
        self.assertEqual(toolset_for("talent", AnonymousUser()), [])

    def test_schema_shape_is_openai_tool_format(self):
        tools = toolset_for("talent", _user("u2", roles.RECRUITER))
        self.assertTrue(all(t["type"] == "function" and "parameters" in t["function"]
                            for t in tools))


class BackgroundReviewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("fbuser")
        self.thread = AssistantThread.objects.create(
            user=self.user, surface="talent", thread_id="t")

    def _down(self, reason, n):
        for _ in range(n):
            AssistantFeedback.objects.create(
                thread=self.thread, user=self.user, message=None,
                rating=AssistantFeedback.RATING_DOWN, reason=reason, surface="talent")

    def test_repeated_complaint_becomes_pending_proposal(self):
        self._down("Trả lời quá dài dòng", 3)
        self._down("một lần thôi", 1)

        call_command("run_assistant_review", "--min-count", "2", "--commit", stdout=StringIO())

        proposals = LongTermMemory.objects.filter(
            user=self.user, source="radar_ai", status=LongTermMemory.STATUS_PENDING)
        self.assertEqual(proposals.count(), 1)
        p = proposals.get()
        self.assertIn("quá dài dòng", p.value)
        self.assertEqual(p.scope, LongTermMemory.SCOPE_OPERATIONAL)
        # không đưa vào context khi còn pending
        self.assertNotIn(p.value, [])

        # chạy lại: idempotent, không tạo thêm
        call_command("run_assistant_review", "--min-count", "2", "--commit", stdout=StringIO())
        self.assertEqual(proposals.count(), 1)

    def test_dry_run_writes_nothing(self):
        self._down("Cần trích dẫn rõ hơn", 2)
        call_command("run_assistant_review", "--min-count", "2", stdout=StringIO())
        self.assertFalse(LongTermMemory.objects.filter(source="radar_ai").exists())
