# -*- coding: utf-8 -*-
"""Đồ thị trạng thái tối giản — engine cho agent core (Master Plan §23.1.1).

Thay `langgraph` bằng ~150 dòng tự chủ, **0 dependency**. Bề mặt API bám sát
LangGraph để chỗ dùng (`ai/graph_agent.py`) gần như không phải đổi:

    g = StateGraph(StateSchema)          # TypedDict; Annotated[T, reducer] -> reducer
    g.add_node("model", model_fn)         # fn: (state: dict) -> dict cập nhật một phần
    g.add_edge(START, "model")
    g.add_conditional_edges("model", route_fn, {"tools": "tools", END: END})
    g.add_edge("tools", "model")
    app = g.compile()
    for state in app.stream(init, config={"recursion_limit": 20}, stream_mode="values"):
        ...

Cố ý KHÔNG có: superstep song song, checkpointer bền (nguồn sự thật là
`AssistantEvent` log), time-travel, subgraph. Cần những thứ đó thì tính lại.
"""
from __future__ import annotations

import typing

START = "__start__"
END = "__end__"

__all__ = ["START", "END", "StateGraph", "CompiledGraph", "GraphRecursionError",
           "interrupt", "Interrupt"]


class GraphRecursionError(RuntimeError):
    """Vượt trần số bước — chống lặp vô hạn."""


class Interrupt(Exception):
    """Node yêu cầu dừng chờ tác nhân ngoài (human-in-the-loop)."""

    def __init__(self, payload=None):
        super().__init__("graph interrupted")
        self.payload = payload


def interrupt(payload=None):
    raise Interrupt(payload)


def _reducers_from_schema(schema):
    """Đọc `Annotated[T, fn]` trong TypedDict → {field: fn}. fn(old, new) -> merged."""
    out = {}
    if schema is None:
        return out
    try:
        hints = typing.get_type_hints(schema, include_extras=True)
    except Exception:                              # noqa: BLE001
        return out
    for name, hint in hints.items():
        args = typing.get_args(hint)
        # Annotated[T, meta...] -> get_args = (T, meta1, ...)
        if len(args) >= 2 and callable(args[1]):
            out[name] = args[1]
    return out


class StateGraph:
    def __init__(self, state_schema=None):
        self._nodes: dict[str, typing.Callable] = {}
        self._edges: dict[str, str] = {}                     # node -> node cố định
        self._cond: dict[str, tuple] = {}                    # node -> (router_fn, mapping)
        self._reducers = _reducers_from_schema(state_schema)

    def add_node(self, name, fn):
        if name in (START, END):
            raise ValueError(f"tên node dành riêng: {name}")
        self._nodes[name] = fn
        return self

    def add_edge(self, src, dst):
        self._edges[src] = dst
        return self

    def add_conditional_edges(self, src, router, mapping=None):
        self._cond[src] = (router, dict(mapping or {}))
        return self

    def set_entry_point(self, name):
        self._edges[START] = name
        return self

    def compile(self):
        if START not in self._edges:
            raise ValueError("chưa có cạnh từ START (add_edge(START, <node>))")
        for name, fn in self._nodes.items():
            if not callable(fn):
                raise ValueError(f"node {name} không phải callable")
        return CompiledGraph(self)


class CompiledGraph:
    def __init__(self, graph: StateGraph):
        self._g = graph

    # ---- merge state ----
    def _merge(self, state: dict, update) -> dict:
        if not update:
            return state
        for key, value in update.items():
            reducer = self._g._reducers.get(key)
            if reducer is not None and key in state and state[key] is not None:
                state[key] = reducer(state[key], value)
            else:
                state[key] = value
        return state

    # ---- routing ----
    def _next(self, node: str, state: dict) -> str:
        if node in self._g._cond:
            router, mapping = self._g._cond[node]
            label = router(state)
            if label in mapping:
                return mapping[label]
            return label            # cho phép trả thẳng tên node hoặc END
        return self._g._edges.get(node, END)

    # ---- run ----
    def stream(self, state, *, config=None, stream_mode="values"):
        """Yield trạng thái sau mỗi node (stream_mode='values').

        `config={"recursion_limit": N}` — trần số bước; vượt → GraphRecursionError.
        Node raise `Interrupt` → yield {"__interrupt__": payload, **state} rồi dừng.
        """
        limit = int((config or {}).get("recursion_limit", 50) or 50)
        state = dict(state)
        node = self._g._edges[START]
        steps = 0
        if stream_mode != "updates":
            yield dict(state)                          # trạng thái ban đầu
        while node != END:
            if steps >= limit:
                raise GraphRecursionError(
                    f"vượt {limit} bước tại node {node!r}")
            steps += 1
            fn = self._g._nodes.get(node)
            if fn is None:
                raise ValueError(f"không có node {node!r}")
            try:
                update = fn(state)
            except Interrupt as exc:
                yield {"__interrupt__": exc.payload, **state}
                return
            state = self._merge(state, update or {})
            if stream_mode == "updates":
                yield {node: update or {}}
            else:
                yield dict(state)
            node = self._next(node, state)

    def invoke(self, state, *, config=None):
        last = dict(state)
        for snapshot in self.stream(state, config=config, stream_mode="values"):
            if "__interrupt__" in snapshot:
                return snapshot
            last = snapshot
        return last
