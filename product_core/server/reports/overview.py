# -*- coding: utf-8 -*-
"""Tổng hợp một trang vận hành duy nhất (Master Plan mục 15).

Trước phase này, "tình hình hệ thống" nằm rải rác ở bốn nơi không ai gộp lại:
`core.views_ui.summary` (đồng bộ Edge), `ai.views.usage_summary` (chi phí AI),
`hiring.metrics.collect` (Talent), `rb.metrics.collect` (RB) — cộng giờ có thêm
`agents` (quan sát agent, Phase 14). Một quản trị viên muốn biết "hệ thống có
đang khoẻ không" phải mở bốn tab.

`collect()` không tính lại logic của bốn nơi đó — chỉ **gọi và gộp**. Sai logic
chỉ số ở một chỗ thì tất cả nơi dùng nó cùng sai theo, dễ phát hiện; tính lại ở
đây một lần nữa thì tạo ra khả năng hai nơi tính ra hai con số khác nhau cho
cùng một câu hỏi — chuyện tệ hơn cả không có dashboard.
"""
from core.models import Edge, SourceRecord
from django.db.models import Count


def collect():
    from hiring import metrics as hiring_metrics
    from rb import metrics as rb_metrics

    from core import capture

    return {
        "sync": _sync(),
        # Nang luc thu thap: day la cho moat ky thuat thanh con so nhin thay
        # duoc (Master Plan muc 9).
        "capture": capture.collect(),
        "ai_usage": _ai_usage(),
        "agents": _agents(),
        "talent": hiring_metrics.collect(),
        "rb": rb_metrics.collect(),
    }


def _sync():
    return {
        "edges": Edge.objects.count(),
        "edges_registered": Edge.objects.exclude(edge_id=None).count(),
        "source_records": SourceRecord.objects.count(),
        "pending_resolution": SourceRecord.objects.filter(
            status=SourceRecord.STATUS_PENDING).count(),
    }


def _ai_usage():
    from ai.models import LLMCall

    total = LLMCall.objects.count()
    if not total:
        return {"total_calls": 0, "failed_calls": 0, "by_provider": []}

    rows = (LLMCall.objects.values("provider")
            .annotate(calls=Count("id")).order_by("-calls"))
    return {
        "total_calls": total,
        "failed_calls": LLMCall.objects.filter(ok=False).count(),
        "by_provider": [{"provider": r["provider"], "calls": r["calls"]}
                        for r in rows],
    }


def _agents():
    """Quan sát Radar Agent Runtime (Phase 14) — tỉ lệ lỗi, thời gian trung vị.

    Không đo "agent chọn đúng tool không" — không có gì để chọn, xem
    `agents/runtime.py`. Đo đúng thứ mục 41 gọi là observability: chạy được
    bao nhiêu lượt, mất bao lâu, lỗi bao nhiêu.
    """
    from agents.models import AgentRun

    finished = AgentRun.objects.exclude(finished_at__isnull=True)
    total = finished.count()
    if not total:
        return {"total_runs": 0, "error_rate": None, "median_ms": None,
                "by_agent": []}

    durations = sorted(
        int((row.finished_at - row.started_at).total_seconds() * 1000)
        for row in finished.only("started_at", "finished_at"))
    median_ms = durations[len(durations) // 2]

    by_agent = list(finished.values("agent")
                    .annotate(runs=Count("id")).order_by("-runs"))

    return {
        "total_runs": total,
        "error_rate": round(
            finished.filter(status=AgentRun.STATUS_ERROR).count() / total, 3),
        "median_ms": median_ms,
        "by_agent": [{"agent": r["agent"], "runs": r["runs"]} for r in by_agent],
    }
