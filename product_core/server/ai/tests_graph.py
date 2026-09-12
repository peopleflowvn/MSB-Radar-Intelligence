# -*- coding: utf-8 -*-
"""Engine đồ thị tự viết `ai/graph.py` (Master Plan §23.1.1)."""
import operator
from typing import Annotated, TypedDict

from django.test import SimpleTestCase

from .graph import (END, START, GraphRecursionError, Interrupt, StateGraph,
                    interrupt)


class _S(TypedDict, total=False):
    trail: Annotated[list, operator.add]
    n: Annotated[int, operator.add]
    label: str
    done: bool


class GraphEngineTest(SimpleTestCase):
    def _lin(self):
        g = StateGraph(_S)
        g.add_node("a", lambda s: {"trail": ["a"], "n": 1})
        g.add_node("b", lambda s: {"trail": ["b"], "n": 1})
        g.add_edge(START, "a")
        g.add_edge("a", "b")
        g.add_edge("b", END)
        return g.compile()

    def test_linear_runs_in_order_and_applies_reducers(self):
        out = self._lin().invoke({"trail": [], "n": 0})
        self.assertEqual(out["trail"], ["a", "b"])
        self.assertEqual(out["n"], 2)

    def test_stream_values_yields_initial_then_each_node(self):
        snaps = list(self._lin().stream({"trail": [], "n": 0}))
        self.assertEqual([s["trail"] for s in snaps], [[], ["a"], ["a", "b"]])

    def test_stream_updates_yields_node_deltas(self):
        snaps = list(self._lin().stream({"trail": []}, stream_mode="updates"))
        self.assertEqual(snaps, [{"a": {"trail": ["a"], "n": 1}},
                                 {"b": {"trail": ["b"], "n": 1}}])

    def test_conditional_edges_route_by_label(self):
        g = StateGraph(_S)
        g.add_node("start", lambda s: {"label": s["label"]})
        g.add_node("left", lambda s: {"trail": ["L"]})
        g.add_node("right", lambda s: {"trail": ["R"]})
        g.add_edge(START, "start")
        g.add_conditional_edges("start", lambda s: s["label"],
                                {"l": "left", "r": "right"})
        g.add_edge("left", END)
        g.add_edge("right", END)
        app = g.compile()
        self.assertEqual(app.invoke({"label": "l", "trail": []})["trail"], ["L"])
        self.assertEqual(app.invoke({"label": "r", "trail": []})["trail"], ["R"])

    def test_router_can_return_END_directly(self):
        g = StateGraph(_S)
        g.add_node("n", lambda s: {"done": True})
        g.add_edge(START, "n")
        g.add_conditional_edges("n", lambda s: END if s.get("done") else "n", {})
        self.assertEqual(g.compile().invoke({})["done"], True)

    def test_cycle_hits_recursion_limit(self):
        g = StateGraph(_S)
        g.add_node("loop", lambda s: {"n": 1})
        g.add_edge(START, "loop")
        g.add_edge("loop", "loop")
        app = g.compile()
        with self.assertRaises(GraphRecursionError):
            list(app.stream({"n": 0}, config={"recursion_limit": 5}))

    def test_recursion_limit_counts_supersteps(self):
        g = StateGraph(_S)
        g.add_node("a", lambda s: {"n": 1})
        g.add_node("b", lambda s: {"n": 1})
        g.add_edge(START, "a")
        g.add_edge("a", "b")
        g.add_edge("b", END)
        # 2 bước, trần 2 -> OK
        self.assertEqual(g.compile().invoke({"n": 0}, config={"recursion_limit": 2})["n"], 2)

    def test_interrupt_stops_and_surfaces_payload(self):
        g = StateGraph(_S)
        g.add_node("a", lambda s: {"trail": ["a"]})
        g.add_node("gate", lambda s: interrupt({"need": "duyệt"}))
        g.add_node("b", lambda s: {"trail": ["b"]})
        g.add_edge(START, "a")
        g.add_edge("a", "gate")
        g.add_edge("gate", "b")
        g.add_edge("b", END)
        snaps = list(g.compile().stream({"trail": []}))
        self.assertIn("__interrupt__", snaps[-1])
        self.assertEqual(snaps[-1]["__interrupt__"], {"need": "duyệt"})
        self.assertEqual(snaps[-1]["trail"], ["a"])          # b chưa chạy

    def test_last_write_wins_without_reducer(self):
        g = StateGraph(_S)
        g.add_node("a", lambda s: {"label": "x"})
        g.add_node("b", lambda s: {"label": "y"})
        g.add_edge(START, "a")
        g.add_edge("a", "b")
        g.add_edge("b", END)
        self.assertEqual(g.compile().invoke({})["label"], "y")

    def test_compile_requires_start_edge(self):
        g = StateGraph(_S)
        g.add_node("a", lambda s: {})
        with self.assertRaises(ValueError):
            g.compile()

    def test_reserved_node_names_rejected(self):
        g = StateGraph(_S)
        with self.assertRaises(ValueError):
            g.add_node(START, lambda s: {})

    def test_raises_when_interrupt_uncaught_via_class(self):
        # Interrupt là Exception — chỗ gọi có thể tự bắt nếu muốn
        self.assertTrue(issubclass(Interrupt, Exception))
