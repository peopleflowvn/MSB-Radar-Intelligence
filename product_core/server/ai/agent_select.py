# -*- coding: utf-8 -*-
"""Chọn bộ chạy agent theo cờ `ASSISTANT_GRAPH` (Master Plan §23.1.1).

`ai/agent.py` (vòng lặp tay) và `ai/graph_agent.py` (LangGraph StateGraph) có
cùng hợp đồng `iter_turn` / `run_turn` / `AgentResult` / `trace_steps` nên thay
được nhau. Mặc định dùng `agent`; bật `ASSISTANT_GRAPH=1` để dùng graph.
"""
from django.conf import settings


def get_runner():
    if getattr(settings, "ASSISTANT_GRAPH", False):
        try:
            from . import graph_agent
            return graph_agent
        except Exception:                          # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "ASSISTANT_GRAPH bật nhưng graph_agent lỗi import — lùi về agent")
    from . import agent
    return agent
