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

    def test_coverage_is_persisted_so_partial_answers_can_be_audited(self):
        """Coverage chỉ nằm trong response thì không rà lại được sau khi đóng tab."""
        claim_id = run_state.claim(self.user, "turn-coverage", 30)
        run_state.finish(claim_id, "done", coverage={
            "method": "deep_read", "candidate_total": 120, "judged": 55,
            "unknown": 3, "not_read": 65, "complete": False,
            "retrieval_degraded": True, "cv_text": "không được lưu"})
        row = AnswerRun.objects.get(pk=claim_id)
        self.assertEqual(row.coverage["not_read"], 65)
        self.assertFalse(row.coverage["complete"])
        self.assertTrue(row.coverage["retrieval_degraded"])
        # Bảng này không được nhận nội dung nghiệp vụ.
        self.assertNotIn("cv_text", row.coverage)

    def test_coverage_is_read_from_a_dataclass_result_not_only_a_dict(self):
        """`AnswerResult` la dataclass: ban dau code goi `.get()` nen nem loi va
        keo theo ca `finish()` khong chay — claim treo o trang thai running."""
        from core.answer.runner import _coverage_of
        from talent.answer.engine import AnswerResult

        coverage = {"method": "deep_read", "candidate_total": 9, "judged": 4,
                    "not_read": 5, "complete": False}
        result = AnswerResult(text="x", trace={"answer_coverage": coverage})
        self.assertEqual(_coverage_of(result), coverage)
        self.assertEqual(_coverage_of({"trace": {"answer_coverage": coverage}}),
                         coverage)
        # Khong co trace, trace sai kieu, hay khong co coverage: tra None chu
        # khong duoc nem — mot dong telemetry khong duoc chan chuyen trang thai.
        self.assertIsNone(_coverage_of(AnswerResult(text="x")))
        self.assertIsNone(_coverage_of({"trace": "khong phai dict"}))
        self.assertIsNone(_coverage_of(None))

    def test_claim_uses_same_id_length_as_persisted_messages(self):
        self.assertIsNotNone(run_state.claim(self.user, "x" * 80, 150))
        self.assertIsNone(run_state.claim(self.user, "x" * 64, 150))
