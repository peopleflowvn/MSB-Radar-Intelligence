"""Runtime helpers for configurable business pipelines."""
from datetime import timedelta

from django.utils import timezone

from .models import WorkflowStage


def stage_for(domain, code):
    return WorkflowStage.objects.filter(domain=domain, code=code).first()


def stage_metadata(domain, code, fallback_label, updated_at=None):
    stage = stage_for(domain, code)
    label = stage.label if stage else fallback_label
    color = stage.color if stage else "#64748b"
    due_at = None
    if stage and stage.sla_hours and updated_at and not stage.is_terminal:
        due_at = updated_at + timedelta(hours=stage.sla_hours)
    return {
        "label": label,
        "color": color,
        "sla_due_at": due_at,
        "is_overdue": bool(due_at and due_at <= timezone.now()),
    }


def validate_stage(domain, code, reason="", from_code=None):
    """Return an end-user error when configured policy rejects a transition."""
    stage = stage_for(domain, code)
    if stage is None:
        return None
    if not stage.is_active:
        return f"Bước '{stage.label}' đang bị tắt trong cấu hình pipeline."
    if stage.requires_reason and not str(reason or "").strip():
        return f"Chuyển sang '{stage.label}' phải ghi lý do."
    current = stage_for(domain, from_code) if from_code else None
    if current and current.allowed_next and code not in current.allowed_next:
        return f"Không được chuyển trực tiếp từ '{current.label}' sang '{stage.label}'."
    return None
