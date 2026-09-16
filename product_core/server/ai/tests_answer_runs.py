from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ai.models import AnswerRun
from talent.answer import run_state


class AnswerRunClaimTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("claim-owner")

    def test_only_first_claim_is_accepted_and_users_are_isolated(self):
        first = run_state.claim(self.user, "turn", 150)
        self.assertIsNotNone(first)
        self.assertIsNone(run_state.claim(self.user, "turn", 150))
        other = get_user_model().objects.create_user("other-owner")
        self.assertIsNotNone(run_state.claim(other, "turn", 150))
        self.assertEqual(AnswerRun.objects.count(), 2)

    def test_expired_turn_is_not_reclaimed_while_provider_might_be_alive(self):
        key = run_state.claim(self.user, "stalled", 150)
        AnswerRun.objects.filter(pk=key).update(deadline=timezone.now() - timedelta(seconds=1))
        self.assertEqual(run_state.status(self.user, "stalled"), "timeout")
        self.assertIsNone(run_state.claim(self.user, "stalled", 150))
        self.assertIsNotNone(run_state.claim(self.user, "new-turn", 150))

    def test_terminal_status_is_immutable_and_survives_cache_loss(self):
        key = run_state.claim(self.user, "done-turn", 150)
        run_state.finish(key, "done")
        run_state.finish(key, "error")
        self.assertEqual(run_state.status(self.user, "done-turn"), "done")
        self.assertIsNone(run_state.claim(self.user, "done-turn", 150))
        self.assertIsNone(run_state.status(self.user, "absent"))
        # Sổ trong tiến trình và cache chia sẻ nay nằm ở khung dùng chung
        # (`core/answer/runner.py`); `talent.answer.runner` chỉ còn phần buộc
        # vào Talent. Tắt cả hai nguồn nhanh để chứng minh trạng thái vẫn đọc
        # được từ bản ghi BỀN — đó là điểm của phép kiểm này.
        from core.answer import runner as core_runner
        from talent.answer import runner
        with mock.patch.object(core_runner, "_INFLIGHT", {}),                 mock.patch.object(core_runner, "_shared_status", return_value=None):
            self.assertEqual(runner.status_of(self.user, "done-turn"), "done")

    def test_claim_uses_same_id_length_as_persisted_messages(self):
        self.assertIsNotNone(run_state.claim(self.user, "x" * 80, 150))
        self.assertIsNone(run_state.claim(self.user, "x" * 64, 150))
