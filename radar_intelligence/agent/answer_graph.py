from __future__ import annotations

from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph


class AnswerState(TypedDict, total=False):
    request: Any
    authorized: bool
    records: tuple
    person_ids: frozenset[str]
    hits: tuple
    evidence: tuple
    result: dict | None


class GroundedAnswerGraph:
    """Durable orchestration boundary for evidence-backed answers.

    Business ownership stays outside this graph. Injected nodes enforce Radar
    scope, retrieve through Haystack, generate, and validate evidence. Keeping
    the state explicit makes retries, checkpoints and approval nodes additive
    without leaking framework types into the public API contract.
    """

    def __init__(
        self,
        prepare: Callable[[Any], dict],
        retrieve: Callable[[dict], dict],
        no_evidence: Callable[[dict], dict],
        generate: Callable[[dict], dict],
    ) -> None:
        graph = StateGraph(AnswerState)
        graph.add_node("authorize_and_scope", prepare)
        graph.add_node("retrieve_evidence", retrieve)
        graph.add_node("answer_without_evidence", no_evidence)
        graph.add_node("generate_and_validate", generate)
        graph.add_edge(START, "authorize_and_scope")
        graph.add_conditional_edges(
            "authorize_and_scope", self._after_scope,
            {"denied": END, "empty": "answer_without_evidence",
             "retrieve": "retrieve_evidence"})
        graph.add_conditional_edges(
            "retrieve_evidence", self._after_retrieval,
            {"empty": "answer_without_evidence", "generate": "generate_and_validate"})
        graph.add_edge("answer_without_evidence", END)
        graph.add_edge("generate_and_validate", END)
        self._compiled = graph.compile()

    @staticmethod
    def _after_scope(state: AnswerState) -> str:
        if not state.get("authorized"):
            return "denied"
        return "retrieve" if state.get("person_ids") else "empty"

    @staticmethod
    def _after_retrieval(state: AnswerState) -> str:
        return "generate" if state.get("evidence") else "empty"

    def invoke(self, request: Any) -> dict | None:
        state = self._compiled.invoke({"request": request})
        return state.get("result")
