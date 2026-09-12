# -*- coding: utf-8 -*-
"""Context projection có version (Master Plan §10.3, §15 Giai đoạn 1).

Toàn bộ message được lưu trong DB nhưng **không** gửi hết cho model. Projection
này là phần thực sự gửi đi: một số lượt gần nhất + summary phần cũ +
`active_criteria` + ID đang nhắc + ghi chú quyền. Có `projection_version` để đổi
cách rút gọn mà vẫn so sánh/replay được.

Là lớp **dẫn xuất**: đọc từ `AssistantMessage` (qua `conversation_state.load`) và
`AssistantThread.state`, không tự lưu trạng thái riêng.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import conversation_state, thread_state

PROJECTION_VERSION = 1


@dataclass
class Projection:
    recent_turns: list = field(default_factory=list)
    summary: str = ""
    active_criteria: dict = field(default_factory=dict)
    constraint_patches: list = field(default_factory=list)
    mentioned_ids: list = field(default_factory=list)
    permissions_note: str = ""
    memories: list = field(default_factory=list)
    #: Snapshot kết quả lượt tìm kiếm gần nhất (`thread_state.last_result_ref`):
    #: {kind, run_id, at, count, items:[{id,name,score,why}]}. Để câu hỏi tiếp
    #: bám được đối tượng ("so sánh 2 người đầu") thay vì parse lại tiêu chí.
    last_result: dict = field(default_factory=dict)
    projection_version: int = PROJECTION_VERSION

    def as_dict(self):
        return {
            "projection_version": self.projection_version,
            "recent_turns": self.recent_turns,
            "summary": self.summary,
            "active_criteria": self.active_criteria,
            "constraint_patches": self.constraint_patches,
            "mentioned_ids": self.mentioned_ids,
            "permissions_note": self.permissions_note,
            "memories": self.memories,
            "last_result": self.last_result,
        }

    def last_result_people(self, limit=12):
        """`[{id, name}]` của lượt trước — cho câu hỏi tiếp bám vào đúng người.

        Nhận cả `items` (shape hiện tại) lẫn `people` (shape cũ một vài chỗ còn
        ghi) để không mất ngữ cảnh trong lúc các call site hội tụ về một khoá.
        """
        raw = self.last_result or {}
        rows = list(raw.get("items") or raw.get("people") or [])[:limit]
        out = []
        for row in rows:
            pid = row.get("id") or row.get("person_id")
            name = row.get("name") or row.get("ten") or ""
            if pid:
                out.append({"id": pid, "name": str(name)})
        return out

    def last_result_lines(self, limit=8):
        """Vài dòng gọn mô tả kết quả gần nhất, hoặc '' nếu không có."""
        raw = self.last_result or {}
        items = list(raw.get("items") or raw.get("people") or [])[:limit]
        if not items:
            return ""
        rows = []
        for index, item in enumerate(items, 1):
            name = str(item.get("name") or item.get("ten") or f"#{item.get('id')}")
            why = str(item.get("why") or item.get("summary") or "").strip()
            rows.append(f"{index}) {name}" + (f" — {why}" if why else ""))
        return "Kết quả tìm kiếm gần nhất: " + " | ".join(rows)

    def context_system(self, max_chars=900):
        """Tầng **context** gộp một message `system`: quyền + memory + summary.

        Tách khỏi tầng stable (persona) và tầng volatile (câu hỏi) — §23.1.2.
        """
        parts = []
        if self.permissions_note:
            parts.append(self.permissions_note)
        if self.memories:
            parts.append("Radar được phép nhớ về người dùng: " + " | ".join(self.memories))
        if self.summary:
            parts.append(f"Tóm tắt hội thoại trước: {self.summary}")
        # Quyền + memory + summary bị kẹp `max_chars`; `last_result` nối SAU và
        # không bị cắt — mất danh sách người vừa hiển thị là mất luôn ngữ cảnh
        # cho câu hỏi tiếp ("so sánh 2 người đầu").
        head = " \n".join(parts)[:max_chars] if parts else ""
        result_lines = self.last_result_lines()
        content = " \n".join(chunk for chunk in (head, result_lines) if chunk)
        if not content:
            return None
        return {"role": "system", "content": content}

    def turn_messages(self, max_turns=8, max_chars=700, last_turn_chars=1600):
        """Các lượt gần nhất, xen kẽ user/assistant (chưa gồm câu hỏi hiện tại).

        Lượt GẦN NHẤT được giữ dài hơn (`last_turn_chars`): câu trả lời phân tích
        ứng viên hay dài, cắt 700 ký tự là mất phần người dùng sẽ hỏi tiếp.
        """
        turns = list(self.recent_turns or [])[-max_turns:]
        out = []
        for index, turn in enumerate(turns):
            cap = last_turn_chars if index == len(turns) - 1 else max_chars
            question = str(turn.get("question") or "").strip()
            answer = str(turn.get("answer") or "").strip()
            if question:
                out.append({"role": "user", "content": question[:cap]})
            if answer:
                out.append({"role": "assistant", "content": answer[:cap]})
        return out

    def context_messages(self, max_turns=8, max_chars=700):
        """Tương thích ngược: context_system + turn_messages."""
        ctx = self.context_system()
        return ([ctx] if ctx else []) + self.turn_messages(max_turns, max_chars)


@dataclass
class ConversationEnvelope:
    """Một lát context thống nhất cho TẤT CẢ model trong một lượt.

    LLM API không có trí nhớ; envelope là hợp đồng để parse, retrieval, rerank
    và answer cùng nhìn một mục tiêu/thao tác criteria thay vì mỗi nhánh tự cắt
    history theo cách riêng.
    """
    thread_id: str = ""
    turn_id: str = ""
    surface: str = "talent"
    question: str = ""
    standalone_question: str = ""
    projection: Projection = field(default_factory=Projection)
    constraint_patches: list = field(default_factory=list)

    def as_dict(self):
        data = self.projection.as_dict()
        data.update({"thread_id": self.thread_id, "turn_id": self.turn_id,
                     "surface": self.surface, "question": self.question,
                     "standalone_question": self.standalone_question,
                     "constraint_patches": self.constraint_patches})
        return data


def _permissions_note(user):
    who = getattr(user, "username", None) or "tài khoản hiện tại"
    return (f"Chỉ dùng dữ liệu mà {who} được phép xem; không suy đoán ngoài phạm vi đó.")


def _user_memories(user, limit=12):
    """Chỉ memory `active`, chưa hết hạn, và không dính prompt-injection (§15 GĐ5)."""
    if not getattr(user, "is_authenticated", False):
        return []
    from django.db.models import Q
    from django.utils import timezone

    from .models import LongTermMemory
    from .prompt_guard import scan as guard_scan
    rows = list(LongTermMemory.objects.filter(
        user=user, status=LongTermMemory.STATUS_ACTIVE
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .order_by("-updated_at")[:limit * 2])

    out, used_ids = [], []
    for row in rows:
        value = str(row.value or "")[:200]
        if not value or guard_scan(value):
            continue
        out.append(value)
        used_ids.append(row.pk)
        if len(out) >= limit:
            break
    if used_ids:
        LongTermMemory.objects.filter(pk__in=used_ids).update(last_used_at=timezone.now())
    return out


def _mentioned_ids(state):
    # v1: chỉ lấy pinned_ids đã chốt. Mở rộng bằng entity linking ở batch sau.
    raw = state.get("pinned_ids") or []
    out = []
    for value in raw:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


def build_context(user, surface, thread_id, client_history=None):
    """Dựng projection cho một lượt. Không gọi model, không ghi gì."""
    row, history, summary, state = conversation_state.load(
        user, surface, thread_id, client_history)
    normalized = thread_state.normalize(state, surface)
    return Projection(
        recent_turns=history,
        summary=summary or "",
        active_criteria=normalized.get("active_criteria") or {},
        constraint_patches=normalized.get("constraint_patches") or [],
        mentioned_ids=_mentioned_ids(normalized),
        permissions_note=_permissions_note(user),
        memories=_user_memories(user),
        last_result=normalized.get("last_result_ref") or {},
    )


def from_turns(history, user=None, surface="talent"):
    """Projection nhẹ khi chỉ có danh sách lượt (chưa/không có thread state)."""
    turns = list(history or [])
    criteria = {}
    for turn in turns:
        if isinstance(turn.get("criteria"), dict) and turn["criteria"]:
            criteria = turn["criteria"]
    return Projection(
        recent_turns=turns,
        active_criteria=criteria,
        permissions_note=_permissions_note(user),
        memories=_user_memories(user),
    )


def build_envelope(user, surface, thread_id, question, *, turn_id="", client_history=None):
    projection = build_context(user, surface, thread_id, client_history)
    standalone = str(question or "").strip()
    # Câu follow-up giữ câu hiện tại nhưng nói rõ criteria đang hiệu lực; layer
    # parse có thể dùng nó để rewrite, còn retrieval không bao giờ mất context.
    if projection.active_criteria:
        standalone = (f"{standalone}\n[Nhu cầu đang hiệu lực: "
                      f"{projection.active_criteria}]")
    return ConversationEnvelope(thread_id=str(thread_id or ""), turn_id=str(turn_id or ""),
                                surface=surface, question=str(question or ""),
                                standalone_question=standalone, projection=projection)
