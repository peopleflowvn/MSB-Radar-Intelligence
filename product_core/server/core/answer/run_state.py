# -*- coding: utf-8 -*-
"""Claim một-lần trong CSDL. KHÔNG bao giờ cấp lại mã lượt đã hết hạn.

Sổ trong tiến trình (`runner._INFLIGHT`) mất khi restart, và cache chia sẻ có
thể bị dọn. Chỉ bản ghi này là bền — nó tồn tại để một lượt đã từng chạy không
thể được khởi động lại dưới cùng `client_turn_id`, kể cả sau khi máy chủ khởi
động lại giữa chừng.

Vì sao không cấp lại lượt hết hạn: "hết hạn" ở đây nghĩa là hạn chót RESPONSE đã
qua, không phải là luồng đã chết — Python không ép dừng được một luồng đang kẹt ở
I/O của nhà cung cấp. Cho gửi lại cùng mã lượt sẽ có hai luồng cùng sinh một câu
trả lời và cùng persist.

Dùng chung mọi domain: bảng chỉ lưu (người dùng, mã lượt, trạng thái, hạn chót),
không có gì thuộc về nghiệp vụ. `client_turn_id` sinh bởi `ai/events.py` là duy
nhất toàn hệ nên Talent và Growth không đụng nhau ở đây.
"""
from datetime import timedelta

from django.utils import timezone

from ai.models import AnswerRun


def claim(user, client_turn_id, seconds):
    row, created = AnswerRun.objects.get_or_create(
        user=user, client_turn_id=str(client_turn_id or "")[:64],
        defaults={"deadline": timezone.now() + timedelta(seconds=seconds)})
    return row.pk if created else None


def finish(claim_id, state, coverage=None):
    """Đóng claim. `coverage` được lưu để rà lại được phạm vi đã trả lời."""
    fields = {"state": state, "updated_at": timezone.now()}
    if isinstance(coverage, dict) and coverage:
        # Chỉ các khoá đã biết: bảng này không được nhận nội dung nghiệp vụ.
        allowed = ("method", "candidate_total", "evaluated", "judged", "unknown",
                   "not_read", "complete", "retrieval_degraded")
        fields["coverage"] = {key: coverage[key] for key in allowed
                             if key in coverage}
    AnswerRun.objects.filter(pk=claim_id, state="running").update(**fields)


def status(user, client_turn_id):
    row = AnswerRun.objects.filter(user=user,
                                   client_turn_id=str(client_turn_id or "")[:64]).first()
    if row is None:
        return None
    if row.state == "running" and row.deadline <= timezone.now():
        return "timeout"
    return row.state
