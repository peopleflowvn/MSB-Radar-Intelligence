# -*- coding: utf-8 -*-
"""Ghi nhật ký sự kiện hội thoại theo lượt (Master Plan §15, Giai đoạn 1).

`TurnRecorder` gom các sự kiện của một lượt (`turn_id` = `client_turn_id` của
client, hoặc một giá trị sinh ra). Ghi hỏng — chưa migrate, chạy ngoài request,
race khi replay — **im lặng bỏ qua**: quan sát không được làm hỏng nghiệp vụ.

`reconstruct_request()` là bằng chứng cho gate "mọi model request dựng lại được
từ event log".
"""
import json
import logging
import uuid

from django.db import IntegrityError

from .models import AssistantEvent

log = logging.getLogger(__name__)

# Alias tiện dùng.
TURN_STARTED = AssistantEvent.KIND_TURN_STARTED
USER_MESSAGE = AssistantEvent.KIND_USER_MESSAGE
INTENT_CLASSIFIED = AssistantEvent.KIND_INTENT_CLASSIFIED
MODEL_REQUESTED = AssistantEvent.KIND_MODEL_REQUESTED
MODEL_RESPONDED = AssistantEvent.KIND_MODEL_RESPONDED
SEARCH_EXECUTED = AssistantEvent.KIND_SEARCH_EXECUTED
SEARCH_RESULTS_RANKED = AssistantEvent.KIND_SEARCH_RESULTS_RANKED
WEB_SEARCHED = AssistantEvent.KIND_WEB_SEARCHED
TOOL_CALLED = AssistantEvent.KIND_TOOL_CALLED
TURN_COMPLETED = AssistantEvent.KIND_TURN_COMPLETED
TURN_FAILED = AssistantEvent.KIND_TURN_FAILED


def new_turn_id():
    return uuid.uuid4().hex[:32]


def _json_safe(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return {"_unserializable": str(value)[:2000]}


class TurnRecorder:
    def __init__(self, thread, turn_id):
        self.thread = thread
        self.turn_id = str(turn_id or "")[:64]
        self._seq = 0

    @property
    def active(self):
        return self.thread is not None and bool(self.turn_id)

    def emit(self, kind, **payload):
        if not self.active:
            return None
        self._seq += 1
        try:
            return AssistantEvent.objects.create(
                thread=self.thread, turn_id=self.turn_id, seq=self._seq,
                kind=kind, payload=_json_safe(payload))
        except IntegrityError:
            # Lượt này đã được ghi (retry/replay). Không phải lỗi.
            return None
        except Exception:                       # noqa: BLE001
            log.exception("Không ghi được AssistantEvent %s", kind)
            return None

    # --- tiện ích theo loại sự kiện -------------------------------------------
    def started(self, **payload):
        return self.emit(TURN_STARTED, **payload)

    def user_message(self, text, **payload):
        return self.emit(USER_MESSAGE, text=str(text)[:10000], **payload)

    def model_requested(self, request, **payload):
        return self.emit(MODEL_REQUESTED, messages=getattr(request, "messages", None),
                         task=getattr(request, "task", ""),
                         params=request.as_kwargs() if hasattr(request, "as_kwargs") else {},
                         meta=getattr(request, "meta", {}) or {},
                         **payload)

    def model_responded(self, response, **payload):
        usage = getattr(response, "usage", None)
        return self.emit(MODEL_RESPONDED,
                         provider=getattr(response, "provider", ""),
                         model=getattr(response, "model", ""),
                         usage=usage.as_dict() if hasattr(usage, "as_dict") else {},
                         latency_ms=getattr(response, "latency_ms", 0),
                         text_chars=len(getattr(response, "text", "") or ""),
                         **payload)

    def intent_classified(self, intent, **payload):
        data = intent.as_dict() if hasattr(intent, "as_dict") else dict(intent or {})
        return self.emit(INTENT_CLASSIFIED, **data, **payload)

    def web_searched(self, *, queries=None, citation_count=0, provider="", model="",
                     **payload):
        # Chỉ ghi truy vấn + số nguồn: KHÔNG ghi nội dung trả về.
        return self.emit(WEB_SEARCHED, queries=list(queries or [])[:8],
                         citation_count=int(citation_count or 0),
                         provider=provider, model=model, **payload)

    def tool_called(self, name, *, ok=True, error="", **payload):
        return self.emit(TOOL_CALLED, name=str(name)[:60], ok=bool(ok),
                         error=str(error)[:200], **payload)

    def search_executed(self, **payload):
        return self.emit(SEARCH_EXECUTED, **payload)

    def search_results_ranked(self, **payload):
        return self.emit(SEARCH_RESULTS_RANKED, **payload)

    def completed(self, **payload):
        return self.emit(TURN_COMPLETED, **payload)

    def failed(self, error, **payload):
        return self.emit(TURN_FAILED, error=str(error)[:500], **payload)


def log_conversation_turn(thread, turn_id, surface, question, reply, *, parent_turn_id=""):
    """Ghi trọn một lượt hội thoại (không phải search) vào event log.

    `reply` là `ai.conversation.ConversationReply`. Best-effort: thread/turn_id
    thiếu thì không ghi gì.
    """
    rec = TurnRecorder(thread, turn_id)
    if not rec.active:
        return rec
    guard_flags = list(getattr(reply, "guard_flags", []) or [])
    rec.started(surface=surface, mode="conversation", guard_flags=guard_flags,
                projection_version=getattr(reply, "projection_version", 0),
                parent_turn_id=str(parent_turn_id or "")[:64] or None)
    rec.user_message(question)
    intent = getattr(reply, "intent", None)
    if intent is not None:
        rec.intent_classified(intent)
    citations = list(getattr(reply, "citations", []) or [])
    if getattr(reply, "web", False) or citations:
        rec.web_searched(
            queries=getattr(reply, "web_queries", None),
            citation_count=len(citations),
            provider=getattr(reply, "provider", ""), model=getattr(reply, "model", ""))
    for call in list(getattr(reply, "tool_trace", []) or []):
        rec.tool_called(call.get("name", ""), ok=call.get("ok", True),
                        error=call.get("error", ""))
    request = getattr(reply, "request", None)
    if request is not None:
        rec.model_requested(request, guard_flags=guard_flags)
        usage = getattr(reply, "usage", None)
        rec.emit(MODEL_RESPONDED,
                 provider=getattr(reply, "provider", ""),
                 model=getattr(reply, "model", ""),
                 usage=usage.as_dict() if hasattr(usage, "as_dict") else {},
                 text_chars=len(str(reply)),
                 has_reasoning=bool(getattr(reply, "reasoning", "")))
    rec.completed(mode="conversation", answer_chars=len(str(reply)))
    return rec


def log_search_turn(thread, turn_id, surface, question, *, criteria=None, provider="",
                    model="", count=0, cache_hit=None, top_score=None, has_reasoning=False,
                    parent_turn_id="", constraint_patches=None, projection_version=None):
    """Ghi trọn một lượt search vào event log (best-effort)."""
    rec = TurnRecorder(thread, turn_id)
    if not rec.active:
        return rec
    rec.started(surface=surface, mode="search",
                parent_turn_id=str(parent_turn_id or "")[:64] or None,
                projection_version=projection_version)
    rec.user_message(question)
    rec.search_executed(criteria=criteria or {}, provider=provider, model=model,
                        cache_hit=cache_hit, constraint_patches=constraint_patches or [])
    rec.search_results_ranked(count=count, top_score=top_score, has_reasoning=has_reasoning)
    rec.completed(mode="search", count=count)
    return rec


def turn_events(thread, turn_id):
    return list(AssistantEvent.objects
                .filter(thread=thread, turn_id=str(turn_id or "")[:64])
                .order_by("seq", "pk"))


def turn_lineage(thread, turn_id, max_depth=20):
    """Chuỗi turn cha → con (retry/branch/undo — §23.1.7). Mới nhất ở cuối."""
    chain, seen = [], set()
    current = str(turn_id or "")[:64]
    while current and current not in seen and len(chain) < max_depth:
        seen.add(current)
        chain.append(current)
        started = AssistantEvent.objects.filter(
            thread=thread, turn_id=current, kind=TURN_STARTED).first()
        current = (started.payload.get("parent_turn_id") if started else None) or ""
    return list(reversed(chain))


def reconstruct_request(thread, turn_id):
    """Dựng lại model request cuối cùng của một lượt từ event log.

    Trả `{"messages", "task", "params"}` hoặc `None` nếu lượt không gọi model.
    """
    last = None
    for event in turn_events(thread, turn_id):
        if event.kind == MODEL_REQUESTED:
            last = event
    if last is None:
        return None
    return {"messages": last.payload.get("messages"),
            "task": last.payload.get("task", ""),
            "params": last.payload.get("params", {})}
