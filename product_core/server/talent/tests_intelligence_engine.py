from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from .answer import engine


@override_settings(INTELLIGENCE_V2_PRIMARY=True)
class IntelligenceEngineRoutingTest(SimpleTestCase):
    @patch("talent.intelligence_client.answer")
    def test_non_attachment_answer_uses_v2_and_preserves_stream_contract(self, v2_answer):
        expected = engine.AnswerResult(text="Grounded", provider="greennode")
        v2_answer.return_value = expected
        chunks = list(engine.stream_answer("Ai phu hop?", user=Mock(pk=7)))
        self.assertEqual(chunks[-1], {"type": "done", "result": expected})
        self.assertEqual(chunks[-2], {"type": "answer", "text": "Grounded"})
        v2_answer.assert_called_once()

    @patch("talent.answer.engine._stream_assess_doc")
    @patch("talent.intelligence_client.answer")
    def test_attachment_keeps_existing_direct_document_path(self, v2_answer, assess):
        # Direct attachment assessment has different evidence provenance and is
        # intentionally not sent through the corpus index.
        assess.return_value = iter((
            {"type": "done", "result": engine.AnswerResult(text="Document")},))
        list(engine.stream_answer(
            "Đánh giá\n\nTÀI LIỆU ĐÍNH KÈM:\nPython", user=Mock(pk=7)))
        v2_answer.assert_not_called()
        assess.assert_called_once()
