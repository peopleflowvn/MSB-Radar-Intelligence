# -*- coding: utf-8 -*-
"""Durable, compact assistant memory without storing CV or PII in the thread.

`AssistantMessage` là lớp đọc; `AssistantThread.state` theo schema `ai.thread_state`
(Master Plan §10.5.1). Số lượt gần nhất giữ trực tiếp lấy từ settings
`ASSISTANT_RECENT_TURNS` (mặc định 16, kẹp trong 8–24).
"""
import re

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import thread_state
from .models import AssistantMessage, AssistantThread

MAX_STORED_TURNS = 24


def _structured_summary(turns, limit):
    """Nén lượt cũ thành facts có thể dùng lại, thay vì chỉ ghép tiêu đề."""
    older = list(turns or [])[:-limit]
    if not older:
        return ""
    exchanges = []
    for item in older[-6:]:
        question = str(item.get("question") or "").strip()[:160]
        answer = str(item.get("answer") or "").strip()[:260]
        if question:
            exchanges.append(f"H: {question}" + (f" — Đ: {answer}" if answer else ""))
    criteria = next((item.get("criteria") for item in reversed(older)
                     if isinstance(item.get("criteria"), dict) and item.get("criteria")), {})
    patches = [patch for item in older[-8:] for patch in (item.get("constraint_patches") or [])
               if isinstance(patch, dict)][-6:]
    parts = ["Mục tiêu/kết luận trước: " + " | ".join(exchanges)]
    if criteria:
        parts.append("Tiêu chí đã chốt: " + str(criteria)[:700])
    if patches:
        parts.append("Thay đổi tiêu chí: " + str(patches)[:700])
    return "\n".join(parts)[:1800]


def recent_turns():
    """Số lượt gần nhất đưa trực tiếp vào context; phần cũ hơn đi qua summary."""
    try:
        value = int(getattr(settings, "ASSISTANT_RECENT_TURNS", 16))
    except (TypeError, ValueError):
        value = 16
    return max(8, min(24, value))


# Giữ tên cũ cho code đang import hằng số này; giá trị theo settings.
RECENT_TURNS = recent_turns()


def normalize_thread_id(value):
    value = re.sub(r"[^a-zA-Z0-9_-]", "", str(value or ""))[:64]
    return value


def load(user, surface, thread_id, client_history=None):
    limit = recent_turns()
    thread_id = normalize_thread_id(thread_id)
    row = None
    if thread_id and getattr(user, "is_authenticated", False):
        row = AssistantThread.objects.filter(
            user=user, surface=surface, thread_id=thread_id).first()
    server_turns = []
    if row:
        messages = list(row.messages.order_by("-created_at", "-pk")[:limit * 2])
        messages.reverse()
        pending_question = ""
        for message in messages:
            if message.role == "user":
                pending_question = message.content
            elif message.role == "assistant" and pending_question:
                server_turns.append({"question": pending_question, "answer": message.content,
                                     "criteria": message.metadata.get("criteria") or {}})
                pending_question = ""
        if not server_turns:
            server_turns = list(row.turns or [])[-limit:]
    client_turns = list(client_history or [])[-limit:]
    # Prefer durable server turns after reload; client turns are newer while the
    # current browser request has not been recorded yet.
    by_question = {}
    for position, turn in enumerate(server_turns + client_turns):
        key = str(turn.get("question") or "").strip().casefold()
        if not key and turn.get("criteria"):
            key = f"criteria:{position}:{turn.get('criteria')}"
        if key:
            by_question[key] = turn
    history = list(by_question.values())[-limit:]
    return row, history, (row.summary if row else ""), (row.state if row else {})


def already_recorded(row, client_turn_id):
    """Lượt client này đã ghi rồi chưa (idempotency — §21.5)."""
    if not client_turn_id:
        return False
    return row.messages.filter(role="user", client_turn_id=client_turn_id).exists()


def record(user, surface, thread_id, question, answer="", criteria=None, mode="search",
           provider="", model="", metadata=None, client_turn_id="", constraint_patches=None,
           last_result=None, pinned_ids=None, user_metadata=None):
    thread_id = normalize_thread_id(thread_id)
    client_turn_id = str(client_turn_id or "")[:64]
    if not thread_id or not getattr(user, "is_authenticated", False):
        return None
    limit = recent_turns()
    with transaction.atomic():
        row, _ = AssistantThread.objects.select_for_update().get_or_create(
            user=user, surface=surface, thread_id=thread_id)

        # Retry cùng một lượt: không ghi lần hai, trả lại thread như cũ.
        if already_recorded(row, client_turn_id):
            return row

        if not row.title:
            row.title = " ".join(str(question).split())[:157]
        message_metadata = {"mode": mode, "criteria": criteria or {},
                            "constraint_patches": constraint_patches or []}
        # Snapshot kết quả để câu hỏi tiếp bám được đối tượng (Master Plan §10.5.1
        # `last_result_ref`); `answer` của lượt search vốn chỉ là "Đã tìm thấy N…".
        if last_result:
            message_metadata["result_snapshot"] = last_result
        message_metadata.update(metadata or {})
        # Correlate the answer without consuming the user-message unique key.
        message_metadata["client_turn_id"] = client_turn_id
        try:
            AssistantMessage.objects.create(
                thread=row, role="user", content=str(question)[:10000],
                metadata={"mode": mode, **(user_metadata or {})},
                client_turn_id=client_turn_id)
        except IntegrityError:
            # Race: một request song song vừa ghi đúng lượt này.
            return row
        AssistantMessage.objects.create(
            thread=row, role="assistant", content=str(answer)[:20000],
            metadata=message_metadata, provider=str(provider or "")[:40],
            model=str(model or "")[:120])

        turns = list(row.turns or [])
        turns.append({"question": str(question)[:1000], "answer": str(answer)[:2000],
                      "criteria": criteria or {}, "mode": mode,
                      "constraint_patches": constraint_patches or []})
        row.turns = turns[-MAX_STORED_TURNS:]
        row.state = thread_state.apply_turn(
            row.state, surface=surface, criteria=criteria, mode=mode,
            constraint_patches=constraint_patches,
            last_result=last_result, pinned_ids=pinned_ids)
        row.summary = _structured_summary(turns, limit)
        row.last_message_at = timezone.now()
        row.save(update_fields=["turns", "state", "summary", "title",
                                "last_message_at", "updated_at"])
    return row
