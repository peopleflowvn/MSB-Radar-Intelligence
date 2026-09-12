"""Database-backed one-shot claims. Never reclaim a timed-out provider's turn ID."""
from datetime import timedelta

from django.utils import timezone

from ai.models import AnswerRun


def claim(user, client_turn_id, seconds):
    row, created = AnswerRun.objects.get_or_create(
        user=user, client_turn_id=str(client_turn_id or "")[:64],
        defaults={"deadline": timezone.now() + timedelta(seconds=seconds)})
    return row.pk if created else None


def finish(claim_id, state):
    AnswerRun.objects.filter(pk=claim_id, state="running").update(
        state=state, updated_at=timezone.now())


def status(user, client_turn_id):
    row = AnswerRun.objects.filter(user=user, client_turn_id=str(client_turn_id or "")[:64]).first()
    if row is None:
        return None
    if row.state == "running" and row.deadline <= timezone.now():
        return "timeout"
    return row.state
