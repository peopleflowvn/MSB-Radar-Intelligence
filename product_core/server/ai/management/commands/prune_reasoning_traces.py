# -*- coding: utf-8 -*-
"""Xoá reasoning_trace và làm sạch payload event cũ (Master Plan §10.4.5, §21.5).

`reasoning_trace` có thể chứa PII và suy luận nhạy cảm nên retention **ngắn hơn**
message. Lệnh này xoá khoá `reasoning_trace` khỏi `AssistantMessage.metadata` cho
message cũ hơn ngưỡng (giữ nguyên message), và tuỳ chọn lược bớt `messages` trong
payload `model.requested` cũ.

    python manage.py prune_reasoning_traces                 # dry-run
    python manage.py prune_reasoning_traces --commit
    python manage.py prune_reasoning_traces --commit --events

Ngưỡng: `--days`, hoặc settings.ASSISTANT_REASONING_RETENTION_DAYS (mặc định 60).
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ai.models import AssistantEvent, AssistantMessage


class Command(BaseCommand):
    help = "Xoá reasoning_trace của message cũ; tuỳ chọn lược payload event cũ."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Ghi thật (mặc định dry-run)")
        parser.add_argument("--days", type=int, default=None,
                            help="Ngưỡng ngày; mặc định settings.ASSISTANT_REASONING_RETENTION_DAYS")
        parser.add_argument("--events", action="store_true",
                            help="Cũng lược 'messages' khỏi payload model.requested cũ")

    def handle(self, *args, **opts):
        days = opts["days"]
        if days is None:
            days = int(getattr(settings, "ASSISTANT_REASONING_RETENTION_DAYS", 60))
        cutoff = timezone.now() - timezone.timedelta(days=days)
        commit = opts["commit"]

        msgs = AssistantMessage.objects.filter(
            created_at__lt=cutoff, metadata__has_key="reasoning_trace")
        msg_count = msgs.count()
        if commit:
            updated = 0
            for message in msgs.iterator():
                meta = dict(message.metadata or {})
                meta.pop("reasoning_trace", None)
                meta["reasoning_trace_pruned"] = True
                message.metadata = meta
                message.save(update_fields=["metadata"])
                updated += 1
            msg_count = updated

        verb = "Đã xoá" if commit else "[DRY-RUN] Sẽ xoá"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} reasoning_trace khỏi {msg_count} message cũ hơn {days} ngày."))

        if opts["events"]:
            events = AssistantEvent.objects.filter(
                created_at__lt=cutoff, kind=AssistantEvent.KIND_MODEL_REQUESTED)
            ev_count = 0
            for event in events.iterator():
                payload = event.payload or {}
                if not payload.get("messages") or payload.get("messages_pruned"):
                    continue
                ev_count += 1
                if commit:
                    payload = dict(payload)
                    payload["messages"] = None
                    payload["messages_pruned"] = True
                    event.payload = payload
                    event.save(update_fields=["payload"])
            verb = "Đã lược" if commit else "[DRY-RUN] Sẽ lược"
            self.stdout.write(self.style.SUCCESS(
                f"{verb} 'messages' khỏi {ev_count} sự kiện model.requested cũ."))

        if not commit and (msg_count or opts["events"]):
            self.stdout.write("Chạy lại với --commit để áp dụng.")
