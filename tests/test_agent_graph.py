import unittest

from radar_intelligence.agent import GroundedAnswerGraph


class GroundedAnswerGraphTests(unittest.TestCase):
    def _graph(self, prepared, calls):
        def prepare(state):
            calls.append("prepare")
            return prepared

        def retrieve(state):
            calls.append("retrieve")
            return {"evidence": ("e1",), "hits": ("h1",)}

        def no_evidence(state):
            calls.append("no_evidence")
            return {"result": {"answer": "empty"}}

        def generate(state):
            calls.append("generate")
            return {"result": {"answer": "grounded"}}

        return GroundedAnswerGraph(prepare, retrieve, no_evidence, generate)

    def test_authorized_scope_retrieves_then_generates(self):
        calls = []
        graph = self._graph({"authorized": True, "person_ids": frozenset({"p1"})}, calls)
        self.assertEqual(graph.invoke(object()), {"answer": "grounded"})
        self.assertEqual(calls, ["prepare", "retrieve", "generate"])

    def test_empty_scope_returns_grounded_empty_answer(self):
        calls = []
        graph = self._graph({"authorized": True, "person_ids": frozenset()}, calls)
        self.assertEqual(graph.invoke(object()), {"answer": "empty"})
        self.assertEqual(calls, ["prepare", "no_evidence"])

    def test_denied_scope_stops_before_retrieval(self):
        calls = []
        graph = self._graph({"authorized": False, "result": None}, calls)
        self.assertIsNone(graph.invoke(object()))
        self.assertEqual(calls, ["prepare"])


if __name__ == "__main__":
    unittest.main()
