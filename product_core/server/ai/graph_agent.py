# -*- coding: utf-8 -*-
"""Agent core dạng đồ thị (Master Plan §23.1.1).

Cùng hợp đồng công khai với `ai/agent.py` (`iter_turn` / `run_turn` / `AgentResult`)
để hai bên thay thế được nhau qua cờ `ASSISTANT_GRAPH`. Khác biệt: vòng lặp
model↔tool được biểu diễn thành **StateGraph** — node là hàm thường, cạnh có điều
kiện quyết định "còn gọi tool hay trả lời".

Engine là `ai/graph.py` (tự viết, 0 dependency). Node gọi thẳng `ai.adapter`;
nguồn sự thật vẫn là `AssistantEvent` log (không checkpointer riêng).
"""
from __future__ import annotations

import logging
import operator
from typing import Annotated, Any, TypedDict

from . import agent as _base
from .graph import END, START, GraphRecursionError, StateGraph
from .adapter import ModelRequest, get_adapter
from .agent import AgentResult, ToolInvocation, max_steps, trace_steps  # re-export
from .conversation import extract_thinking
from .persona import STABLE_PROMPT_VERSION
from .toolset import agent_toolset_for, dispatch

log = logging.getLogger(__name__)

__all__ = ["iter_turn", "run_turn", "trace_steps", "AgentResult", "ToolInvocation"]


class _State(TypedDict, total=False):
    messages: Annotated[list, operator.add]
    tool_events: Annotated[list, operator.add]
    steps: Annotated[int, operator.add]
    up: Annotated[int, operator.add]
    uc: Annotated[int, operator.add]
    answer: str
    reasoning: str
    provider: str
    model: str
    calls: list           # tool_calls của lượt model gần nhất (last-write)
    last_request: Any     # ModelRequest cuối — cho events.reconstruct_request()
    done: bool
    errored: bool


def _build_graph(*, model, tool_schema, user, surface, context):
    def model_node(state: _State) -> dict:
        messages = list(state.get("messages") or [])
        request = ModelRequest(
            messages=messages, task="assistant_agent",
            temperature=0.2, max_tokens=900, tools=tool_schema,
            extra={"budget_seconds": 45},
            meta={"stable_prompt_version": STABLE_PROMPT_VERSION,
                  "agent_step": (state.get("steps") or 0) + 1})
        try:
            resp = model.complete(request)
        except Exception as exc:                       # noqa: BLE001
            log.info("graph_agent: model lỗi: %s", exc)
            return {"steps": 1, "done": True, "errored": True, "answer": "",
                    "last_request": request}

        msg = _base._message_from_response(resp)
        calls = _base._tool_calls(msg)
        up = int(getattr(getattr(resp, "usage", None), "prompt_tokens", 0) or 0)
        uc = int(getattr(getattr(resp, "usage", None), "completion_tokens", 0) or 0)
        out: dict[str, Any] = {"steps": 1, "up": up, "uc": uc,
                               "provider": resp.provider or "",
                               "model": resp.model or "", "calls": calls,
                               "last_request": request}
        if calls:
            out["messages"] = [{"role": "assistant",
                                "content": (msg or {}).get("content") or "",
                                "tool_calls": calls}]
            return out
        clean, reasoning = extract_thinking(
            resp.text or (msg or {}).get("content") or "")
        out["answer"] = str(clean or "").strip()[:3000]
        out["reasoning"] = reasoning[:6000]
        out["done"] = True
        return out

    def tools_node(state: _State) -> dict:
        tool_msgs, events = [], []
        for call in state.get("calls") or []:
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            arguments = _base_json(fn.get("arguments"))
            outcome = dispatch(name, arguments, user=user, surface=surface,
                               context=context or {})
            payload = outcome.payload()
            inv = ToolInvocation(name=name, arguments=arguments, ok=outcome.ok,
                                 summary=_base._summarise(payload),
                                 error="" if outcome.ok else outcome.error)
            events.append(inv.as_dict())
            tool_msgs.append({"role": "tool",
                              "tool_call_id": call.get("id") or name,
                              "content": _base._summarise(payload)})
        return {"messages": tool_msgs, "tool_events": events, "calls": []}

    def route(state: _State) -> str:
        if state.get("done") or not state.get("calls"):
            return END
        return "tools"

    g = StateGraph(_State)
    g.add_node("model", model_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "model")
    g.add_conditional_edges("model", route, {"tools": "tools", END: END})
    g.add_edge("tools", "model")
    return g.compile()


def _base_json(raw):
    import json
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {"_": v}
    except (TypeError, ValueError):
        return {}


def _result_from_state(state: _State) -> AgentResult:
    from .adapter import ModelUsage
    res = AgentResult(
        text=str(state.get("answer") or "").strip()[:3000],
        reasoning=str(state.get("reasoning") or "").strip()[:6000],
        provider=state.get("provider") or "", model=state.get("model") or "",
        steps=int(state.get("steps") or 0),
        usage=ModelUsage(int(state.get("up") or 0), int(state.get("uc") or 0)),
        last_request=state.get("last_request"))
    for ev in state.get("tool_events") or []:
        res.tool_trace.append(ToolInvocation(
            name=ev.get("name", ""), arguments=ev.get("arguments", {}),
            ok=ev.get("ok", False), summary=ev.get("summary", ""),
            error=ev.get("error", "")))
    return res


def _force_final(model, messages, result):
    """Hết đệ quy mà model vẫn gọi tool → ép một lượt trả lời không kèm tool."""
    req = ModelRequest(messages=list(messages) + [{
        "role": "user",
        "content": "Đã đủ dữ liệu. Trả lời câu hỏi ngắn gọn bằng tiếng Việt, "
                   "không gọi thêm tool."}],
        task="assistant_agent", temperature=0.2, max_tokens=800,
        extra={"budget_seconds": 45})
    result.last_request = req
    try:
        resp = model.complete(req)
        clean, reasoning = extract_thinking(resp.text)
        result.text = str(clean or "").strip()[:3000] or result.text
        result.reasoning = (result.reasoning + " " + reasoning).strip()[:6000]
        result.provider = resp.provider or result.provider
        result.model = resp.model or result.model
    except Exception:                                  # noqa: BLE001
        result.text = result.text or ("Radar đã thu thập dữ liệu nhưng chưa "
                                      "tổng hợp được câu trả lời.")


def iter_turn(question, *, surface="talent", user=None, projection=None,
              adapter=None, system=None, context=None, cancel=None, tools=None):
    """Generator {"type": "tool"|"answer"|"error"|"done", ...} — như `agent.iter_turn`."""
    model = adapter or get_adapter()
    tool_schema = tools if tools is not None else agent_toolset_for(surface, user)
    if not tool_schema:
        result = AgentResult()
        yield from _base._finish_plain(model, question, surface, user, projection,
                                       system, result)
        return

    messages = _base._base_messages(question, surface=surface, user=user,
                                    projection=projection, system=system)
    graph = _build_graph(model=model, tool_schema=tool_schema, user=user,
                         surface=surface, context=context)
    limit = max_steps()
    cfg = {"recursion_limit": limit * 2 + 3}
    init: _State = {"messages": messages}

    emitted_tools = 0
    last_state: _State = init
    hit_limit = False
    try:
        for state in graph.stream(init, config=cfg, stream_mode="values"):
            last_state = state
            events = state.get("tool_events") or []
            while emitted_tools < len(events):
                yield {"type": "tool", "tool": events[emitted_tools]}
                emitted_tools += 1
            if cancel is not None and cancel():
                res = _result_from_state(state)
                res.cancelled = True
                yield {"type": "done", "result": res}
                return
    except GraphRecursionError:
        hit_limit = True
    except Exception as exc:                            # noqa: BLE001
        log.info("graph_agent: stream lỗi: %s", exc)
        yield {"type": "error", "text": "Đồ thị agent gặp lỗi."}

    result = _result_from_state(last_state)
    if last_state.get("errored"):
        yield {"type": "error", "text": "Không gọi được mô hình."}
    if hit_limit or (not result.text and result.tool_trace):
        _force_final(model, last_state.get("messages") or messages, result)
    if result.text:
        yield {"type": "answer", "text": result.text}
    yield {"type": "done", "result": result}


def run_turn(question, *, surface="talent", user=None, projection=None, adapter=None,
             system=None, context=None, cancel=None, tools=None) -> AgentResult:
    result = AgentResult()
    for event in iter_turn(question, surface=surface, user=user, projection=projection,
                           adapter=adapter, system=system, context=context,
                           cancel=cancel, tools=tools):
        if event.get("type") == "done":
            return event["result"]
    return result
