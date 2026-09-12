from django.contrib.auth.models import User
from django.test import TestCase

from . import conversation_state
from .models import AssistantMessage, AssistantThread


class AssistantConversationStateTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("assistant-memory")

    def test_thread_remembers_recent_turns_and_criteria(self):
        window = conversation_state.recent_turns()
        total = window + 4
        for number in range(total):
            conversation_state.record(
                self.user, "talent", "thread-1", f"question {number}",
                f"answer {number}", {"location": f"place {number}"})
        row, history, summary, state = conversation_state.load(
            self.user, "talent", "thread-1")
        self.assertIsNotNone(row)
        self.assertEqual(len(history), window)
        # Lượt cũ hơn cửa sổ rơi vào summary, không vào history.
        self.assertIn("question 0", summary)
        self.assertEqual(state["active_criteria"]["location"], f"place {total - 1}")
        self.assertEqual(state["criteria"]["location"], f"place {total - 1}")
        self.assertEqual(state["turn_count"], total)
        self.assertEqual(state["schema_version"], 2)

    def test_constraint_patches_are_durable_and_summarized(self):
        patch = {"op": "REMOVE", "field": "location", "value": "Hà Nội"}
        for number in range(conversation_state.recent_turns() + 1):
            conversation_state.record(
                self.user, "talent", "thread-patches", f"question {number}", "answer",
                {"title": "RM"}, constraint_patches=[patch] if number == 0 else [])
        _row, _history, summary, state = conversation_state.load(
            self.user, "talent", "thread-patches")
        self.assertEqual(state["constraint_patches"], [patch])
        self.assertIn("Thay đổi tiêu chí", summary)

    def test_thread_is_isolated_by_user_and_surface(self):
        conversation_state.record(self.user, "talent", "same", "talent")
        conversation_state.record(self.user, "prospect", "same", "prospect")
        self.assertEqual(AssistantThread.objects.count(), 2)

    def test_client_turn_id_makes_record_idempotent(self):
        first = conversation_state.record(
            self.user, "talent", "thread-idem", "câu hỏi", "trả lời",
            client_turn_id="turn-abc")
        again = conversation_state.record(
            self.user, "talent", "thread-idem", "câu hỏi", "trả lời",
            client_turn_id="turn-abc")
        self.assertEqual(first.pk, again.pk)
        # Một lượt = một message user + một message assistant, không nhân đôi.
        self.assertEqual(
            AssistantMessage.objects.filter(thread=first, role="user").count(), 1)
        self.assertEqual(first.turns and len(first.turns), 1)

    def test_missing_client_turn_id_still_records_every_turn(self):
        conversation_state.record(self.user, "talent", "t", "q1", "a1")
        conversation_state.record(self.user, "talent", "t", "q2", "a2")
        thread = AssistantThread.objects.get(user=self.user, surface="talent", thread_id="t")
        self.assertEqual(
            AssistantMessage.objects.filter(thread=thread, role="user").count(), 2)
