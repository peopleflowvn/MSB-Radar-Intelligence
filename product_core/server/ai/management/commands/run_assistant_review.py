# -*- coding: utf-8 -*-
"""Background review — chỉ tạo ĐỀ XUẤT compact (Master Plan §15 GĐ5, §23.1.6).

Quét 👎 feedback gần đây; khi cùng một người phàn nàn cùng một lý do ≥ N lần,
tạo MỘT `LongTermMemory` ở `status=pending_review` (`source=radar_ai`) gợi ý Radar
ghi nhớ điều đó. Người dùng duyệt mới có hiệu lực.

    python manage.py run_assistant_review --since-days 14 --min-count 2

KHÔNG có tool ghi dữ liệu nghiệp vụ / export / đổi quyền. Chạy thủ công hoặc theo
cron; mặc định không tự chạy. Idempotent (dedup theo key), có quota.
"""
import hashlib
import re

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from ai.models import AssistantFeedback, LongTermMemory

_PROPOSAL_QUOTA_PER_USER = 10


def _key(reason):
    slug = re.sub(r"[^a-z0-9]+", "-", reason.lower()).strip("-")[:40]
    return f"review-{slug}-{hashlib.sha1(reason.encode('utf-8')).hexdigest()[:8]}"


class Command(BaseCommand):
    help = "Sinh đề xuất memory (pending_review) từ phản hồi 👎 lặp lại."

    def add_arguments(self, parser):
        parser.add_argument("--since-days", type=int, default=14)
        parser.add_argument("--min-count", type=int, default=2)
        parser.add_argument("--commit", action="store_true", help="Ghi thật (mặc định dry-run)")

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timezone.timedelta(days=opts["since_days"])
        rows = (AssistantFeedback.objects
                .filter(rating=AssistantFeedback.RATING_DOWN, created_at__gte=cutoff)
                .exclude(reason="").exclude(user__isnull=True)
                .values("user_id", "reason", "surface")
                .annotate(n=Count("id"))
                .filter(n__gte=opts["min_count"])
                .order_by("-n"))

        proposed = skipped = 0
        for row in rows:
            key = _key(row["reason"])
            exists = LongTermMemory.objects.filter(user_id=row["user_id"], key=key).exists()
            quota_hit = LongTermMemory.objects.filter(
                user_id=row["user_id"], status=LongTermMemory.STATUS_PENDING,
                source="radar_ai").count() >= _PROPOSAL_QUOTA_PER_USER
            if exists or quota_hit:
                skipped += 1
                continue
            proposed += 1
            self.stdout.write(
                f"  [đề xuất] user {row['user_id']} ×{row['n']}: {row['reason'][:80]}")
            if opts["commit"]:
                LongTermMemory.objects.create(
                    user_id=row["user_id"], scope=LongTermMemory.SCOPE_OPERATIONAL,
                    kind=LongTermMemory.KIND_PREFERENCE,
                    status=LongTermMemory.STATUS_PENDING, source="radar_ai",
                    surface=row["surface"] or "", key=key,
                    value=(f"Người dùng đã phản hồi chưa tốt {row['n']} lần với lý do: "
                           f"“{row['reason'][:200]}”. Cân nhắc điều chỉnh cách trả lời cho phù hợp."))

        verb = "Đã tạo" if opts["commit"] else "[DRY-RUN] Sẽ tạo"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {proposed} đề xuất; bỏ qua {skipped} (đã có / quá quota)."))
