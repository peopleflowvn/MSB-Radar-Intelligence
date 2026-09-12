# -*- coding: utf-8 -*-
"""Agent core — vòng lặp gọi tool dùng chung cho mọi bề mặt (Master Plan §23.1.1).

Một lượt hội thoại "có kỹ năng" = nhiều lần gọi model xen kẽ thực thi tool:

    model → (tool_calls?) → dispatch từng tool → nối kết quả → model → … → câu trả lời

Độc lập nhà cung cấp: đi qua `ai.adapter` như mọi chỗ khác; tool_calls đọc từ
`ModelResponse.raw` (payload OpenAI). Tôn trọng:

* trần `max_steps` — chống lặp vô hạn / chi phí;
* hợp đồng huỷ — `cancel()` trả True giữa các bước thì dừng, trả phần dở;
* tool chỉ-đọc / chỉ-đề-xuất, lọc RBAC ở `toolset` trước khi model thấy.

`run_turn()` trả `AgentResult`. `iter_turn()` là generator phát sự kiện cho SSE
(`{"type": "tool"|"answer"|"done"}`).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from django.conf import settings

from . import toolset
from .adapter import ModelRequest, ModelUsage, get_adapter
from .conversation import extract_thinking
from .persona import STABLE_PROMPT_VERSION, stable_system

log = logging.getLogger(__name__)

_DEFAULT_MAX_STEPS = 4
_TOOL_RESULT_CHARS = 2000


@dataclass
class ToolInvocation:
    name: str
    arguments: dict
    ok: bool
    summary: str = ""
    error: str = ""

    def as_dict(self):
        return {"name": self.name, "arguments": self.arguments, "ok": self.ok,
                "summary": self.summary[:400], "error": self.error[:200]}


@dataclass
class AgentResult:
    text: str = ""
    reasoning: str = ""
    tool_trace: list = field(default_factory=list)   # [ToolInvocation]
    provider: str = ""
    model: str = ""
    usage: ModelUsage = field(default_factory=ModelUsage)
    steps: int = 0
    cancelled: bool = False
    #: ModelRequest cuối cùng đã gửi — để events.reconstruct_request().
    last_request: object = None

    @property
    def used_tools(self):
        return bool(self.tool_trace)

    def trace_dicts(self):
        return [t.as_dict() for t in self.tool_trace]


_TOOL_LABEL = {
    "read_allowed_evidence": "Đọc bằng chứng hồ sơ",
    "remember_proposal": "Đề xuất ghi nhớ",
    "feedback": "Ghi nhận đánh giá",
    "compare_candidates": "So sánh ứng viên",
    "canonical_lookup": "Chuẩn hoá giá trị",
    "fact_provenance": "Truy nguồn gốc dữ liệu",
    "draft_outreach": "Soạn nháp tiếp cận",
    "enrich_company_from_web": "Tra thông tin công ty (web)",
}


def trace_steps(tool_trace):
    """[{name,ok,error,...}] → [{label, detail}] cho ThinkingProcess."""
    out = []
    for call in tool_trace or []:
        name = call.get("name", "")
        label = _TOOL_LABEL.get(name, f"Tool: {name}")
        detail = ("" if call.get("ok", True)
                  else f"lỗi: {call.get('error', '')}")[:200]
        out.append({"label": label, "detail": detail})
    return out


def max_steps():
    try:
        return max(1, int(getattr(settings, "ASSISTANT_TOOL_MAX_STEPS", _DEFAULT_MAX_STEPS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_STEPS


def _base_messages(question, *, surface, user, projection, system):
    msgs = [{"role": "system", "content": system or stable_system(surface, user)}]
    if projection is not None:
        ctx = projection.context_system()
        if ctx:
            msgs.append(ctx)
        msgs.extend(projection.turn_messages())
    msgs.append({"role": "user", "content": str(question)[:2000]})
    return msgs


def _message_from_response(response):
    """Lấy assistant message (kèm tool_calls) từ payload provider; None nếu không có."""
    raw = getattr(response, "raw", None) or {}
    choices = raw.get("choices") or []
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message")
        if isinstance(msg, dict):
            return msg
    return None


def _tool_calls(msg):
    calls = (msg or {}).get("tool_calls") or []
    return [c for c in calls if isinstance(c, dict) and c.get("function")]


def _summarise(payload):
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    return text[:_TOOL_RESULT_CHARS]


def iter_turn(question, *, surface="talent", user=None, projection=None,
              adapter=None, system=None, context=None, cancel=None, tools=None):
    """Generator: yield {"type": "tool"|"answer"|"error"|"done", ...}.

    Chunk cuối luôn là {"type": "done", "result": AgentResult}.
    """
    model = adapter or get_adapter()
    tool_schema = tools if tools is not None else toolset.agent_toolset_for(surface, user)
    result = AgentResult()

    if not tool_schema:
        # Không có tool nào khả dụng → một lượt trả lời thường.
        yield from _finish_plain(model, question, surface, user, projection, system, result)
        return

    messages = _base_messages(question, surface=surface, user=user,
                              projection=projection, system=system)
    limit = max_steps()

    for step in range(1, limit + 1):
        if cancel is not None and cancel():
            result.cancelled = True
            result.steps = step - 1
            yield {"type": "done", "result": result}
            return
        result.steps = step
        request = ModelRequest(
            messages=list(messages), task="assistant_agent",
            temperature=0.2, max_tokens=900, tools=tool_schema,
            extra={"budget_seconds": 45},
            meta={"stable_prompt_version": STABLE_PROMPT_VERSION,
                  "agent_step": step})
        result.last_request = request
        try:
            response = model.complete(request)
        except Exception as exc:                   # noqa: BLE001
            log.info("agent: lỗi gọi model bước %s: %s", step, exc)
            yield {"type": "error", "text": "Không gọi được mô hình."}
            result.text = result.text or ""
            yield {"type": "done", "result": result}
            return

        _accumulate(result, response)
        msg = _message_from_response(response)
        calls = _tool_calls(msg)

        if not calls:
            clean, reasoning = extract_thinking(response.text or (msg or {}).get("content") or "")
            result.text = str(clean or "").strip()[:3000]
            result.reasoning = (result.reasoning + " " + reasoning).strip()[:6000]
            if result.text:
                yield {"type": "answer", "text": result.text}
            yield {"type": "done", "result": result}
            return

        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            try:
                arguments = json.loads(fn.get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    arguments = {"_": arguments}
            except (TypeError, ValueError):
                arguments = {}
            outcome = toolset.dispatch(name, arguments, user=user, surface=surface,
                                       context=context or {})
            payload = outcome.payload()
            inv = ToolInvocation(name=name, arguments=arguments, ok=outcome.ok,
                                 summary=_summarise(payload),
                                 error="" if outcome.ok else outcome.error)
            result.tool_trace.append(inv)
            yield {"type": "tool", "tool": inv.as_dict()}
            messages.append({"role": "tool", "tool_call_id": call.get("id") or name,
                             "content": _summarise(payload)})

    # Hết số bước mà model vẫn gọi tool → ép một lượt trả lời không kèm tool.
    final = ModelRequest(messages=messages + [{
        "role": "user",
        "content": "Đã đủ dữ liệu. Trả lời câu hỏi ngắn gọn bằng tiếng Việt, "
                   "không gọi thêm tool."}],
        task="assistant_agent", temperature=0.2, max_tokens=800,
        extra={"budget_seconds": 45})
    result.last_request = final
    try:
        response = model.complete(final)
        _accumulate(result, response)
        clean, reasoning = extract_thinking(response.text)
        result.text = str(clean or "").strip()[:3000]
        result.reasoning = (result.reasoning + " " + reasoning).strip()[:6000]
    except Exception:                             # noqa: BLE001
        result.text = result.text or "Radar đã thu thập dữ liệu nhưng chưa tổng hợp được câu trả lời."
    if result.text:
        yield {"type": "answer", "text": result.text}
    yield {"type": "done", "result": result}


def _finish_plain(model, question, surface, user, projection, system, result):
    from .conversation import build_conversation_request
    request, _flags = build_conversation_request(
        question, surface=surface, user=user, projection=projection)
    if system:
        request.messages[0] = {"role": "system", "content": system}
    result.last_request = request
    try:
        response = model.complete(request)
    except Exception:                             # noqa: BLE001
        result.text = ("Radar chưa gọi được mô hình để trả lời phần này.")
        yield {"type": "answer", "text": result.text}
        yield {"type": "done", "result": result}
        return
    _accumulate(result, response)
    clean, reasoning = extract_thinking(response.text)
    result.text = str(clean or response.text or "").strip()[:3000]
    result.reasoning = reasoning[:6000]
    if result.text:
        yield {"type": "answer", "text": result.text}
    yield {"type": "done", "result": result}


def _accumulate(result, response):
    result.provider = response.provider or result.provider
    result.model = response.model or result.model
    usage = getattr(response, "usage", None)
    if usage is not None:
        result.usage = ModelUsage(
            result.usage.prompt_tokens + int(getattr(usage, "prompt_tokens", 0) or 0),
            result.usage.completion_tokens + int(getattr(usage, "completion_tokens", 0) or 0))


def run_turn(question, *, surface="talent", user=None, projection=None, adapter=None,
             system=None, context=None, cancel=None, tools=None) -> AgentResult:
    """Chạy trọn vòng lặp, trả `AgentResult`."""
    result = AgentResult()
    for event in iter_turn(question, surface=surface, user=user, projection=projection,
                           adapter=adapter, system=system, context=context,
                           cancel=cancel, tools=tools):
        if event.get("type") == "done":
            return event["result"]
    return result
