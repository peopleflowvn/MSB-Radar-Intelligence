# -*- coding: utf-8 -*-
"""Retention cho hội thoại trợ lý (Master Plan §14, §21.5).

Chốt một thời hạn mặc định: hội thoại **đã archive** và không có hoạt động mới
quá ngưỡng thì soft-delete (xoá cứng cả message + event log qua CASCADE). Hội
thoại đang hoạt động (chưa archive) không đụng tới — người dùng vẫn mở lại được.

    python manage.py prune_conversations                 # dry-run
    python manage.py prune_conversations --commit
    python manage.py prune_conversations --commit --include-active   # cả chưa archive

Ngưỡng: `--days`, hoặc settings.ASSISTANT_CONVERSATION_RETENTION_DAYS (mặc định 365).
Mỗi lượt xoá ghi một dòng AccessLog (action=delete) để Compliance truy được.
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import AccessLog
from ai.models import AssistantThread


class Command(BaseCommand):
    help = "Xoá hội thoại archive đã quá hạn retention (có AccessLog)."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Ghi thật (mặc định dry-run)")
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--include-active", action="store_true",
                            help="Xoá cả hội thoại chưa archive nếu quá hạn (mặc định KHÔNG)")

    def handle(self, *args, **opts):
        days = opts["days"]
        if days is None:
            days = int(getattr(settings, "ASSISTANT_CONVERSATION_RETENTION_DAYS", 365))
        cutoff = timezone.now() - timezone.timedelta(days=days)
        commit = opts["commit"]

        qs = AssistantThread.objects.filter(updated_at__lt=cutoff)
        if not opts["include_active"]:
            qs = qs.filter(archived=True)

        total = qs.count()
        removed = 0
        if commit:
            for thread in qs.iterator():
                self._audit(thread)
                thread.delete()
                removed += 1

        verb = "Đã xoá" if commit else "[DRY-RUN] Sẽ xoá"
        scope = "" if opts["include_active"] else " (chỉ archive)"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {removed or total} hội thoại{scope} không hoạt động quá {days} ngày."))
        if not commit and total:
            self.stdout.write("Chạy lại với --commit để áp dụng.")

    def _audit(self, thread):
        try:
            AccessLog.objects.create(
                user=thread.user, user_name=str(thread.user)[:150],
                action=AccessLog.ACTION_DELETE, module="ai",
                object_type="assistant_thread", object_id=str(thread.thread_id)[:64],
                path="manage.py prune_conversations", method="JOB",
                extra={"surface": thread.surface, "reason": "retention",
                       "message_count": thread.messages.count(),
                       "event_count": thread.events.count(),
                       "last_activity": thread.updated_at.isoformat()})
        except Exception:                       # noqa: BLE001
            self.stderr.write(f"Không ghi được AccessLog cho thread {thread.thread_id}")
