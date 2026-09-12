# -*- coding: utf-8 -*-
"""Dựng `AssistantMessage` từ `AssistantThread.turns` cũ (Master Plan §10.1, bước 3).

Các thread tạo trước khi có bảng message chỉ có JSON `turns`. Lệnh này sinh cặp
message user/assistant tương ứng để `conversation_state.load` và sidebar đọc được
theo message thay vì rơi về `turns`.

Mặc định **dry-run**: chỉ báo cáo. Thêm `--commit` để ghi thật.

    python manage.py backfill_assistant_messages            # xem trước
    python manage.py backfill_assistant_messages --commit
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ai.models import AssistantMessage, AssistantThread


class Command(BaseCommand):
    help = "Sinh AssistantMessage từ AssistantThread.turns cũ (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true",
                            help="Ghi thật; mặc định chỉ dry-run")
        parser.add_argument("--limit", type=int, default=0,
                            help="Chỉ xử lý N thread đầu (0 = tất cả)")

    def handle(self, *args, **opts):
        commit = opts["commit"]
        qs = (AssistantThread.objects
              .exclude(turns=[])
              .order_by("pk"))
        if opts["limit"]:
            qs = qs[:opts["limit"]]

        scanned = skipped_has_messages = skipped_empty = 0
        threads_written = messages_written = 0

        for thread in qs.iterator():
            scanned += 1
            turns = [t for t in (thread.turns or []) if isinstance(t, dict)]
            if not turns:
                skipped_empty += 1
                continue
            if thread.messages.exists():
                # Đã có message (dual-write hoặc lần backfill trước) — không đụng.
                skipped_has_messages += 1
                continue

            pairs = self._pairs_from_turns(turns)
            messages_written += len(pairs)
            threads_written += 1
            if commit:
                self._write(thread, pairs)

        verb = "Đã ghi" if commit else "[DRY-RUN] Sẽ ghi"
        self.stdout.write(
            f"Quét {scanned} thread có turns. "
            f"Bỏ qua {skipped_has_messages} (đã có message), {skipped_empty} (turns rỗng).")
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {messages_written} message cho {threads_written} thread."))
        if not commit and threads_written:
            self.stdout.write("Chạy lại với --commit để áp dụng.")

    def _pairs_from_turns(self, turns):
        rows = []
        for turn in turns:
            question = str(turn.get("question") or "").strip()
            answer = str(turn.get("answer") or "").strip()
            mode = str(turn.get("mode") or "search")
            criteria = turn.get("criteria") or {}
            if question:
                rows.append(("user", question[:10000], {"mode": mode}))
            if answer:
                rows.append(("assistant", answer[:20000],
                             {"mode": mode, "criteria": criteria, "backfilled": True}))
        return rows

    @transaction.atomic
    def _write(self, thread, pairs):
        # created_at do auto_now_add đặt; thứ tự giữ theo pk tăng dần.
        AssistantMessage.objects.bulk_create([
            AssistantMessage(thread=thread, role=role, content=content, metadata=meta)
            for role, content, meta in pairs
        ])
        if not thread.last_message_at:
            thread.last_message_at = timezone.now()
            thread.save(update_fields=["last_message_at", "updated_at"])
